import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from harbor.viewer.scanner import JobScanner

JOBS_DIR = Path(__file__).resolve().parents[2] / "jobs"
KNOWN_VARIANTS = {"mcp", "cli", "skill", "mcpc"}
GROUP_KEYS = ["job", "variant", "task", "agent", "model"]

# Channel-matching logic mirrored from
# tasks/apify-fetch-actor-id/tests/check.py:_matches_channel.
# Copied (not imported) because check.py runs inside the verifier container
# and depends on rewardkit + a fixed /logs path; keep both in sync manually.
# Differences vs check.py (latent bugs in check.py worth porting back):
#   - lower-case function name (Claude Code emits `Bash`, check.py compares `"bash"`)
#   - mcp channel also matches `mcp__apify__*` (Claude Code's MCP naming),
#     not just the `apify_*` style used by other harnesses.
VARIANT_CHANNEL = {"mcp": "mcp", "cli": "cli", "mcpc": "mcpc", "skill": "cli"}


def matches_channel(name: str, args: dict, channel: str) -> bool:
    name_l = (name or "").lower()
    cmd = ((args or {}).get("command") or "").lstrip()
    if channel == "mcp":
        return name_l.startswith("apify_") or name_l.startswith("mcp__apify__")
    if channel == "cli":
        return name_l == "bash" and cmd.startswith("apify ")
    if channel == "mcpc":
        return name_l == "bash" and cmd.startswith("mcpc ")
    return False

st.set_page_config(page_title="mcp-evals dashboard", layout="wide")
st.title("mcp-evals dashboard")


def parse_variant(job_name: str) -> str:
    # Naming convention (AGENTS.md): <dataset>-<harness>-<model>-<tool>-<purpose>.
    # The tool is one of KNOWN_VARIANTS; scan tokens for the first match.
    for tok in job_name.split("-"):
        if tok in KNOWN_VARIANTS:
            return tok
    return "?"


@st.cache_data(show_spinner=False)
def load_trial_timeline(job_name: str, trial_name: str, mtime: float) -> dict:
    # Reads agent/trajectory.json and returns:
    #   line:   [{t, cum_tokens}] one point per step (for the cumulative line)
    #   marks:  [{t, cum_tokens, name, args}] one point per tool call (markers)
    #   n_steps, n_tool_calls
    # `t` is seconds from the trial's first step.
    del mtime
    traj_path = JOBS_DIR / job_name / trial_name / "agent" / "trajectory.json"
    empty = {"line": [], "marks": [], "n_steps": 0, "n_tool_calls": 0}
    if not traj_path.exists():
        return empty
    try:
        steps = json.loads(traj_path.read_text()).get("steps", [])
    except (json.JSONDecodeError, OSError):
        return empty
    line: list[dict] = []
    marks: list[dict] = []
    t0: datetime | None = None
    cum = 0
    for s in steps:
        ts = s.get("timestamp")
        if not ts:
            continue
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t0 is None:
            t0 = when
        t = (when - t0).total_seconds()
        step_id = s.get("step_id")
        m = s.get("metrics") or {}
        # prompt_tokens per-call already includes history; we still cumsum to
        # reflect total billed token consumption (matches the cost chart).
        cum += (m.get("prompt_tokens") or 0) + (m.get("completion_tokens") or 0)
        line.append({"t": t, "step": step_id, "cum_tokens": cum})
        for tc in (s.get("tool_calls") or []):
            marks.append({
                "t": t,
                "step": step_id,
                "cum_tokens": cum,
                "name": tc.get("function_name") or "?",
                "args": tc.get("arguments") or {},
            })
    return {
        "line": line,
        "marks": marks,
        "n_steps": len(steps),
        "n_tool_calls": len(marks),
    }


@st.cache_data(show_spinner=False)
def load_trial_rows(job_name: str, mtime: float) -> list[dict]:
    # mtime in the cache key invalidates when the job dir changes.
    del mtime
    scanner = JobScanner(JOBS_DIR)
    out: list[dict] = []
    for trial_name in scanner.list_trials(job_name):
        tr = scanner.get_trial_result(job_name, trial_name)
        if tr is None:
            continue
        n_in, n_cache, n_out, cost = tr.compute_token_cost_totals()
        errored = tr.exception_info is not None
        rewards = (
            tr.verifier_result.rewards
            if tr.verifier_result and tr.verifier_result.rewards
            else None
        )
        reward = sum(rewards.values()) / len(rewards) if rewards else 0.0

        def _secs(ti):
            if ti is None or ti.started_at is None or ti.finished_at is None:
                return 0.0
            return (ti.finished_at - ti.started_at).total_seconds()
        model_name = None
        if tr.config and tr.config.agent:
            model_name = tr.config.agent.model_name
        out.append({
            "job": job_name,
            "trial": trial_name,
            "variant": parse_variant(job_name),
            "task": tr.task_name,
            "agent": tr.agent_info.name if tr.agent_info else None,
            "model": model_name,
            "reward": reward,
            "errored": errored,
            "n_input": n_in or 0,
            "n_cache": n_cache or 0,
            "n_output": n_out or 0,
            "cost_usd": cost or 0.0,
            "t_env_setup": _secs(tr.environment_setup),
            "t_agent_setup": _secs(tr.agent_setup),
            "t_agent_exec": _secs(tr.agent_execution),
            "t_verifier": _secs(tr.verifier),
        })
    return out


def aggregate(trials: list[dict], by: list[str]) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {
        "reward_sum": 0.0, "errored": 0, "total": 0,
        "cost_usd": 0.0, "n_input": 0, "n_cache": 0, "n_output": 0,
        "t_env_setup": 0.0, "t_agent_setup": 0.0, "t_agent_exec": 0.0, "t_verifier": 0.0,
    })
    for t in trials:
        key = " | ".join(str(t.get(b) or "?") for b in by)
        g = groups[key]
        g["total"] += 1
        if t["errored"]:
            g["errored"] += 1
        g["reward_sum"] += t["reward"]
        g["cost_usd"] += t["cost_usd"]
        g["n_input"] += t["n_input"]
        g["n_cache"] += t["n_cache"]
        g["n_output"] += t["n_output"]
        g["t_env_setup"] += t["t_env_setup"]
        g["t_agent_setup"] += t["t_agent_setup"]
        g["t_agent_exec"] += t["t_agent_exec"]
        g["t_verifier"] += t["t_verifier"]
    rows = []
    for key, g in groups.items():
        total = g["total"] or 1
        rows.append({
            "group": key,
            "total": g["total"],
            "errored": g["errored"],
            "avg_reward": g["reward_sum"] / total,
            "cost_usd": g["cost_usd"],
            "input_tokens": g["n_input"],
            "cache_tokens": g["n_cache"],
            "output_tokens": g["n_output"],
            "env_setup_s": g["t_env_setup"],
            "agent_setup_s": g["t_agent_setup"],
            "agent_exec_s": g["t_agent_exec"],
            "verifier_s": g["t_verifier"],
        })
    rows.sort(key=lambda r: r["group"])
    return rows


job_dirs = (
    sorted(
        (p for p in JOBS_DIR.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if JOBS_DIR.exists()
    else []
)
all_jobs = [d.name for d in job_dirs]
if not all_jobs:
    st.warning(f"No jobs found in {JOBS_DIR}")
    st.stop()

selected = st.sidebar.multiselect("Jobs", all_jobs, default=all_jobs[:5])
selected = sorted(selected, key=all_jobs.index)
if not selected:
    st.info("Pick at least one job in the sidebar.")
    st.stop()

mtimes = {p.name: p.stat().st_mtime for p in job_dirs}
trials: list[dict] = []
for name in selected:
    trials.extend(load_trial_rows(name, mtimes.get(name, 0.0)))

if not trials:
    st.warning("Selected jobs have no trial results yet.")
    st.stop()

tab_grouped, tab_trials = st.tabs(["Grouped", "Trial details"])

with tab_grouped:
    group_by = st.multiselect("Group by", GROUP_KEYS, default=["job"])
    if not group_by:
        st.info("Pick at least one grouping dimension.")
    else:
        rows = aggregate(trials, group_by)

        st.subheader(f"Summary (grouped by {' | '.join(group_by)})")
        st.dataframe(rows, use_container_width=True)

        st.subheader("Avg reward")
        fig = px.bar(rows, x="group", y="avg_reward", hover_data=["errored", "total"])
        fig.update_xaxes(title=" | ".join(group_by))
        fig.update_yaxes(range=[0, 1])
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Cost (USD)")
        fig_cost = px.bar(rows, x="group", y="cost_usd", hover_data=["input_tokens", "cache_tokens", "output_tokens"])
        fig_cost.update_xaxes(title=" | ".join(group_by))
        st.plotly_chart(fig_cost, use_container_width=True)

        st.subheader("Duration (s)")
        # Summed per-phase seconds across trials in the group. NOTE: trials run in
        # parallel, so this is not wall-clock time.
        duration_rows = []
        for r in rows:
            duration_rows.append({"group": r["group"], "phase": "env setup", "seconds": r["env_setup_s"]})
            duration_rows.append({"group": r["group"], "phase": "agent setup", "seconds": r["agent_setup_s"]})
            duration_rows.append({"group": r["group"], "phase": "agent exec", "seconds": r["agent_exec_s"]})
            duration_rows.append({"group": r["group"], "phase": "verifier", "seconds": r["verifier_s"]})
        fig_dur = px.bar(
            duration_rows,
            x="group",
            y="seconds",
            color="phase",
            barmode="stack",
            category_orders={"phase": ["env setup", "agent setup", "agent exec", "verifier"]},
        )
        fig_dur.update_xaxes(title=" | ".join(group_by))
        st.plotly_chart(fig_dur, use_container_width=True)

        st.subheader("Token usage")
        # n_input_tokens includes cache; uncached = input - cache. See harbor/viewer/server.py:_uncached_input.
        token_rows = []
        for r in rows:
            n_in = r["input_tokens"] or 0
            n_cache = r["cache_tokens"] or 0
            n_out = r["output_tokens"] or 0
            token_rows.append({"group": r["group"], "kind": "input (cached)", "tokens": n_cache})
            token_rows.append({"group": r["group"], "kind": "input (uncached)", "tokens": max(0, n_in - n_cache)})
            token_rows.append({"group": r["group"], "kind": "output", "tokens": n_out})
        fig_tokens = px.bar(
            token_rows,
            x="group",
            y="tokens",
            color="kind",
            barmode="stack",
            category_orders={"kind": ["input (cached)", "input (uncached)", "output"]},
            color_discrete_map={
                "input (cached)": "#9ecae1",
                "input (uncached)": "#d62728",
                "output": "#2ca02c",
            },
        )
        fig_tokens.update_xaxes(title=" | ".join(group_by))
        st.plotly_chart(fig_tokens, use_container_width=True)

with tab_trials:
    task_names = sorted({t["task"] for t in trials if t.get("task")})
    if not task_names:
        st.info("No tasks found in the selected trials.")
    else:
        picked_task = st.selectbox("Task", task_names)
        x_axis = st.selectbox("X axis", ["time (s)", "step", "trial"], index=0)
        only_channel = st.checkbox("Show only channel events", value=False)
        task_trials = [t for t in trials if t["task"] == picked_task]
        # Style: color = variant, dash = (model, agent). Trials sharing all three
        # render identically (intentional). Each distinct (variant, model, agent)
        # combination contributes a single legend entry.
        palette = px.colors.qualitative.Plotly
        dash_cycle = ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"]
        variants_seen = sorted({t["variant"] for t in task_trials})
        ma_seen = sorted({(t.get("model") or "?", t.get("agent") or "?") for t in task_trials})
        color_for = {v: palette[i % len(palette)] for i, v in enumerate(variants_seen)}
        dash_for = {ma: dash_cycle[i % len(dash_cycle)] for i, ma in enumerate(ma_seen)}
        legend_shown: set[tuple] = set()
        fig_tl = go.Figure()
        table_rows = []
        tool_call_rows = []
        for trial_idx, t in enumerate(task_trials, start=1):
            tl = load_trial_timeline(t["job"], t["trial"], mtimes.get(t["job"], 0.0))
            label = f"{t['job']} / {t['trial']}"
            expected_channel = VARIANT_CHANNEL.get(t["variant"])
            channel_flags = [
                matches_channel(m["name"], m["args"], expected_channel) if expected_channel else False
                for m in tl["marks"]
            ]
            for m, is_channel in zip(tl["marks"], channel_flags):
                tool_call_rows.append({
                    "trial": t["trial"],
                    "variant": t["variant"],
                    "t_s": round(m["t"], 2),
                    "cum_tokens": m["cum_tokens"],
                    "tool": m["name"],
                    "args": json.dumps(m["args"])[:300],
                    "channel": "✓" if is_channel else "",
                })
            table_rows.append({
                "trial": t["trial"],
                "job": t["job"],
                "variant": t["variant"],
                "model": t["model"],
                "reward": t["reward"],
                "errored": t["errored"],
                "steps": tl["n_steps"],
                "tool_calls": tl["n_tool_calls"],
                "input_tokens": t["n_input"],
                "cache_tokens": t["n_cache"],
                "output_tokens": t["n_output"],
                "cost_usd": t["cost_usd"],
                "agent_exec_s": t["t_agent_exec"],
            })
            if not tl["line"]:
                continue
            variant = t["variant"]
            ma = (t.get("model") or "?", t.get("agent") or "?")
            style_key = (variant, ma)
            color = color_for[variant]
            dash = dash_for[ma]
            group_label = f"{variant} | {ma[0]} / {ma[1]}"
            show_legend = style_key not in legend_shown
            legend_shown.add(style_key)

            def _x(r):
                if x_axis == "step":
                    return r.get("step")
                if x_axis == "trial":
                    return t["trial"]
                return r["t"]

            if x_axis != "trial":
                fig_tl.add_trace(go.Scatter(
                    x=[_x(r) for r in tl["line"]],
                    y=[r["cum_tokens"] for r in tl["line"]],
                    mode="lines",
                    name=group_label,
                    legendgroup=group_label,
                    showlegend=show_legend,
                    line=dict(color=color, dash=dash),
                    hovertemplate="x=%{x}<br>tokens=%{y}<extra>" + label + "</extra>",
                ))
            visible_marks = [
                (m, is_ch) for m, is_ch in zip(tl["marks"], channel_flags)
                if not only_channel or is_ch
            ]
            if visible_marks:
                fig_tl.add_trace(go.Scatter(
                    x=[_x(m) for m, _ in visible_marks],
                    y=[m["cum_tokens"] for m, _ in visible_marks],
                    mode="markers",
                    name=group_label,
                    legendgroup=group_label,
                    # In trial mode there's no line trace, so the markers have
                    # to carry the legend entry themselves.
                    showlegend=(x_axis == "trial" and show_legend),
                    marker=dict(size=8, symbol="circle", color=color),
                    customdata=[[m["name"], json.dumps(m["args"])[:300]] for m, _ in visible_marks],
                    hovertemplate="x=%{x}<br>tokens=%{y}<br><b>%{customdata[0]}</b><br>%{customdata[1]}<extra>" + label + "</extra>",
                ))
        if not fig_tl.data:
            st.info("No trajectory.json found for trials of this task.")
        else:
            xaxis_title = {"time (s)": "seconds from trial start", "step": "step id", "trial": "trial"}[x_axis]
            fig_tl.update_xaxes(title=xaxis_title)
            fig_tl.update_yaxes(title="cumulative tokens (sum of per-call prompt + completion)")
            st.plotly_chart(fig_tl, use_container_width=True)
        st.dataframe(table_rows, use_container_width=True)
        st.subheader("Tool calls")
        if tool_call_rows:
            meta_for = {t["trial"]: t for t in task_trials}
            trial_names = sorted({r["trial"] for r in tool_call_rows})

            def _label(name: str) -> str:
                t = meta_for.get(name, {})
                return (
                    f"{t.get('variant', '?')} | {t.get('model', '?')} / {t.get('agent', '?')} "
                    f"- reward={t.get('reward', 0):.2f} - {name}"
                )

            picked_trial = st.selectbox("Trial", trial_names, format_func=_label)
            filtered = [
                {
                    "t_s": r["t_s"],
                    "channel": r["channel"],
                    "tool": r["tool"],
                    "args": r["args"],
                    "cum_tokens": r["cum_tokens"],
                }
                for r in tool_call_rows
                if r["trial"] == picked_trial and (not only_channel or r["channel"])
            ]
            st.dataframe(filtered, use_container_width=True)
        else:
            st.info("No tool calls recorded for trials of this task.")
