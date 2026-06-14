import importlib.util
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from harbor.viewer.scanner import JobScanner

REPO_ROOT = Path(__file__).resolve().parents[2]
# Set by `mcp-evals dashboard` so external projects can point at their own jobs dir.
JOBS_DIR = Path(os.environ.get("MCP_EVALS_JOBS_DIR", REPO_ROOT / "jobs")).expanduser().resolve()
# Fallback parse for jobs predating MCP_EVALS_INTEGRATION in verifier env.
KNOWN_INTEGRATION_TYPES = {"mcp", "cli", "skill", "mcpc"}
GROUP_KEYS = ["trial", "job", "integration", "integration_type", "integration_target", "task", "agent", "model"]

# Shared trajectory-metric logic (stdlib-only). Loaded by file path because the
# dashboard venv has streamlit+harbor but not the mcp_evals package, and
# importing the package would also trigger its harbor monkey-patches.
_spec = importlib.util.spec_from_file_location(
    "mcp_evals_metrics", REPO_ROOT / "src" / "mcp_evals" / "metrics.py"
)
metrics_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metrics_mod)

st.set_page_config(page_title="mcp-evals dashboard", layout="wide")
# Widen the sidebar and let multiselect chips show full job names instead of ellipsing.
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] { width: 520px !important; min-width: 520px !important; }
    section[data-testid="stSidebar"] span[data-baseweb="tag"] { max-width: none !important; }
    section[data-testid="stSidebar"] span[data-baseweb="tag"] > div { max-width: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("mcp-evals dashboard")


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _fallback_integration_type(job_name: str) -> str:
    # Used only when the trial's verifier env lacks MCP_EVALS_INTEGRATION.
    # Naming convention (AGENTS.md): <dataset>-<harness>-<model>-<tool>-<purpose>.
    for tok in job_name.split("-"):
        if tok in KNOWN_INTEGRATION_TYPES:
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
        channel = None
        integration = None
        if tr.config and tr.config.verifier:
            channel = tr.config.verifier.env.get("EXPECTED_CHANNEL") or None
            integration = tr.config.verifier.env.get("MCP_EVALS_INTEGRATION") or None
        integration_target, integration_type = metrics_mod.parse_integration(integration)
        if integration_target is None:
            integration_target = metrics_mod.target_for_task(tr.task_name or "")
        if integration_type is None:
            integration_type = _fallback_integration_type(job_name)
        trial_dir = JOBS_DIR / job_name / trial_name
        details = read_json(trial_dir / "verifier" / "reward-details.json")
        passed = metrics_mod.tests_passed(details)
        traj = read_json(trial_dir / "agent" / "trajectory.json") or {}
        trial_metrics, per_call = metrics_mod.compute_trial_metrics(traj, channel, integration_target)
        values = metrics_mod.call_values(per_call)

        def _secs(ti):
            if ti is None or ti.started_at is None or ti.finished_at is None:
                return 0.0
            return (ti.finished_at - ti.started_at).total_seconds()
        model_name = None
        if tr.config and tr.config.agent:
            model_name = tr.config.agent.model_name
        reward = None
        if tr.verifier_result and tr.verifier_result.rewards:
            reward = tr.verifier_result.rewards.get("reward")
        model_info = tr.agent_info.model_info if tr.agent_info else None
        out.append({
            "job": job_name,
            "trial": trial_name,
            "integration": integration or "?",
            "integration_type": integration_type,
            "integration_target": integration_target,
            "channel": channel,
            "task": tr.task_name,
            "agent": tr.agent_info.name if tr.agent_info else None,
            "model": model_name,
            "source": tr.source,
            "model_provider": model_info.provider if model_info else None,
            "model_name_short": model_info.name if model_info else None,
            "trial_uri": tr.trial_uri,
            "started_at": tr.started_at,
            "finished_at": tr.finished_at,
            "reward": reward,
            "tests_passed": bool(passed) and not errored,
            "failed_criteria": ", ".join(metrics_mod.failed_criteria(details)),
            "errored": errored,
            "exception": tr.exception_info.exception_type if tr.exception_info else "",
            "escape_call_values": values["escape_call_values"],
            "errored_call_values": values["errored_call_values"],
            "n_input": n_in or 0,
            "n_cache": n_cache or 0,
            "n_output": n_out or 0,
            "cost_usd": cost or 0.0,
            "t_env_setup": _secs(tr.environment_setup),
            "t_agent_setup": _secs(tr.agent_setup),
            "t_agent_exec": _secs(tr.agent_execution),
            "t_verifier": _secs(tr.verifier),
            **trial_metrics,
        })
    return out


def aggregate(trials: list[dict], by: list[str]) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {
        "passed": 0, "errored": 0, "total": 0,
        "cost_usd": 0.0, "n_input": 0, "n_cache": 0, "n_output": 0,
        "t_env_setup": 0.0, "t_agent_setup": 0.0, "t_agent_exec": 0.0, "t_verifier": 0.0,
        "agent_turns": 0, "channel_calls": 0, "off_channel_calls": 0,
        "errored_calls": 0, "channel_output_chars": 0,
        "baseline_sum": 0, "baseline_n": 0,
    })
    for t in trials:
        key = " | ".join(str(t.get(b) or "?") for b in by)
        g = groups[key]
        g["total"] += 1
        if t["errored"]:
            g["errored"] += 1
        if t["tests_passed"]:
            g["passed"] += 1
        g["cost_usd"] += t["cost_usd"]
        g["n_input"] += t["n_input"]
        g["n_cache"] += t["n_cache"]
        g["n_output"] += t["n_output"]
        g["t_env_setup"] += t["t_env_setup"]
        g["t_agent_setup"] += t["t_agent_setup"]
        g["t_agent_exec"] += t["t_agent_exec"]
        g["t_verifier"] += t["t_verifier"]
        g["agent_turns"] += t["agent_turns"]
        g["channel_calls"] += t["channel_calls"]
        g["off_channel_calls"] += t["off_channel_calls"]
        g["errored_calls"] += t["errored_calls"]
        g["channel_output_chars"] += t["channel_output_chars"]
        if t["prompt_baseline_tokens"]:
            g["baseline_sum"] += t["prompt_baseline_tokens"]
            g["baseline_n"] += 1
    rows = []
    for key, g in groups.items():
        total = g["total"] or 1
        rows.append({
            "group": key,
            "total": g["total"],
            "passed": g["passed"],
            "errored": g["errored"],
            "pass_rate": g["passed"] / total,
            "avg_agent_turns": g["agent_turns"] / total,
            "avg_channel_calls": g["channel_calls"] / total,
            "avg_off_channel_calls": g["off_channel_calls"] / total,
            "avg_errored_calls": g["errored_calls"] / total,
            "avg_channel_output_chars": g["channel_output_chars"] / total,
            # ~tokens at 4 chars/token; codex trials lack per-step metrics (None baseline)
            "avg_prompt_baseline_tokens": (
                g["baseline_sum"] / g["baseline_n"] if g["baseline_n"] else None
            ),
            "cost_usd": g["cost_usd"],
            "avg_cost_usd": g["cost_usd"] / total,
            "input_tokens": g["n_input"],
            "cache_tokens": g["n_cache"],
            "uncached_input_tokens": max(0, g["n_input"] - g["n_cache"]),
            "output_tokens": g["n_output"],
            "avg_input_tokens": g["n_input"] / total,
            "avg_cache_tokens": g["n_cache"] / total,
            "avg_uncached_input_tokens": max(0, g["n_input"] - g["n_cache"]) / total,
            "avg_output_tokens": g["n_output"] / total,
            "cache_hit_rate": g["n_cache"] / g["n_input"] if g["n_input"] else None,
            "env_setup_s": g["t_env_setup"],
            "agent_setup_s": g["t_agent_setup"],
            "agent_exec_s": g["t_agent_exec"],
            "verifier_s": g["t_verifier"],
            "avg_env_setup_s": g["t_env_setup"] / total,
            "avg_agent_setup_s": g["t_agent_setup"] / total,
            "avg_agent_exec_s": g["t_agent_exec"] / total,
            "avg_verifier_s": g["t_verifier"] / total,
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

@st.cache_data(show_spinner=False)
def _job_trial_count(job_name: str, mtime: float) -> int:
    del mtime
    return len(JobScanner(JOBS_DIR).list_trials(job_name))


job_mtimes = {d.name: d.stat().st_mtime for d in job_dirs}
trial_counts = {j: _job_trial_count(j, job_mtimes[j]) for j in all_jobs}
default_jobs = set(all_jobs[:5])
st.sidebar.markdown("**Jobs**")
with st.sidebar.container(height=320):
    selected = [
        j for j in all_jobs
        if st.checkbox(f"{j} ({trial_counts[j]})", value=j in default_jobs, key=f"job_cb_{j}")
    ]
selected = sorted(selected, key=all_jobs.index)
harbor_view_base = st.sidebar.text_input(
    "Harbor view base URL", value="http://127.0.0.1:8080",
    help="Base URL of `harbor view jobs`. Used to link trials to their detail page.",
).rstrip("/")
if not selected:
    st.info("Pick at least one job in the sidebar.")
    st.stop()
# Efficiency of a failed trial is noise; default to comparing passed trials only.
passed_only = st.sidebar.checkbox("Efficiency metrics: passed trials only", value=True)

mtimes = {p.name: p.stat().st_mtime for p in job_dirs}
trials: list[dict] = []
for name in selected:
    trials.extend(load_trial_rows(name, mtimes.get(name, 0.0)))

if not trials:
    st.warning("Selected jobs have no trial results yet.")
    st.stop()

tab_grouped, tab_trials, tab_grid = st.tabs(["Grouped", "Trials", "Token grid"])

with tab_grouped:
    group_by = st.multiselect("Group by", GROUP_KEYS, default=["trial"])
    if not group_by:
        st.info("Pick at least one grouping dimension.")
    else:
        rows = aggregate(trials, group_by)
        eff_trials = [t for t in trials if t["tests_passed"]] if passed_only else trials
        eff_rows = aggregate(eff_trials, group_by) if eff_trials else []
        eff_note = " (passed trials only)" if passed_only else ""
        if passed_only:
            st.caption(f"Efficiency charts cover {len(eff_trials)}/{len(trials)} trials "
                       "(passed only); pass rate always covers all.")

        st.subheader(f"Summary (grouped by {' | '.join(group_by)})")
        # Averages only: comparable across groups with different trial counts.
        # aggregate() still returns the sums (charts hover, other consumers);
        # cost_usd stays as the one total with natural sum semantics (job spend).
        SUMMARY_COLUMNS = [
            "group", "total", "passed", "errored", "pass_rate",
            "avg_agent_turns", "avg_channel_calls", "avg_off_channel_calls",
            "avg_errored_calls", "avg_channel_output_chars", "avg_prompt_baseline_tokens",
            "avg_cost_usd", "avg_uncached_input_tokens", "avg_cache_tokens", "cache_hit_rate", "avg_output_tokens",
            "avg_env_setup_s", "avg_agent_setup_s", "avg_agent_exec_s", "avg_verifier_s",
            "cost_usd",
        ]
        st.dataframe(
            [{k: r[k] for k in SUMMARY_COLUMNS} for r in rows],
            use_container_width=True,
        )

        st.subheader("Pass rate")
        # All verifier criteria true and no trial exception. Health gate, not an
        # optimization target: anything under 1.0 deserves a look at the trial.
        fig = px.bar(rows, x="group", y="pass_rate", hover_data=["passed", "errored", "total"])
        fig.update_xaxes(title=" | ".join(group_by))
        fig.update_yaxes(range=[0, 1])
        st.plotly_chart(fig, use_container_width=True)

        if not eff_rows:
            st.warning("No passed trials in the selection; efficiency charts are empty. "
                       "Untick 'passed trials only' to include failed trials.")

        st.subheader(f"Channel activity (avg per trial){eff_note}")
        activity_rows = []
        for r in eff_rows:
            activity_rows.append({"group": r["group"], "metric": "channel calls", "value": r["avg_channel_calls"]})
            activity_rows.append({"group": r["group"], "metric": "off-channel calls", "value": r["avg_off_channel_calls"]})
            activity_rows.append({"group": r["group"], "metric": "errored calls", "value": r["avg_errored_calls"]})
            activity_rows.append({"group": r["group"], "metric": "agent turns", "value": r["avg_agent_turns"]})
        if activity_rows:
            fig_act = px.bar(activity_rows, x="group", y="value", color="metric", barmode="group")
            fig_act.update_xaxes(title=" | ".join(group_by))
            st.plotly_chart(fig_act, use_container_width=True)

        st.subheader(f"Channel output size (avg chars per trial){eff_note}")
        # Verbosity of the target surface: total tool-result chars of on-channel
        # calls. ~tokens = chars / 4. Caveat: opencode truncates huge bash
        # outputs in the trajectory, so cli numbers can undercount (see README
        # known limitations).
        output_rows = [
            {
                "group": r["group"],
                "chars": r["avg_channel_output_chars"],
                "est_tokens": int(r["avg_channel_output_chars"] / 4),
            }
            for r in eff_rows
        ]
        if output_rows:
            fig_out = px.bar(output_rows, x="group", y="chars", hover_data=["est_tokens"])
            fig_out.update_xaxes(title=" | ".join(group_by))
            st.plotly_chart(fig_out, use_container_width=True)

        # The calls behind the off-channel / errored counts, plus failed tests
        # and trial exceptions. All selected trials, not just eff_trials: a
        # failed trial's escapes are exactly what you want to inspect.
        flagged = []
        for t in trials:
            for v in t["escape_call_values"]:
                flagged.append({"trial": t["trial"], "job": t["job"], "what": "escape", "value": v})
            for v in t["errored_call_values"]:
                flagged.append({"trial": t["trial"], "job": t["job"], "what": "errored call", "value": v})
            if t["failed_criteria"]:
                flagged.append({"trial": t["trial"], "job": t["job"], "what": "failed test", "value": t["failed_criteria"]})
            if t["exception"]:
                flagged.append({"trial": t["trial"], "job": t["job"], "what": "exception", "value": t["exception"]})
        if flagged:
            st.subheader("Flagged: escapes, errored calls, failed tests, exceptions")
            st.dataframe(flagged, use_container_width=True)

        st.subheader("Prompt baseline tokens (avg first-step prompt)")
        # Fixed context overhead: system prompt + tool schemas + instruction.
        # The MCP schema tax shows up here. None for codex (no per-step metrics).
        baseline_rows = [
            {"group": r["group"], "tokens": r["avg_prompt_baseline_tokens"]}
            for r in rows if r["avg_prompt_baseline_tokens"]
        ]
        if baseline_rows:
            fig_base = px.bar(baseline_rows, x="group", y="tokens")
            fig_base.update_xaxes(title=" | ".join(group_by))
            st.plotly_chart(fig_base, use_container_width=True)
        else:
            st.info("No per-step token metrics in the selected trials (codex trajectories lack them).")

        if eff_rows:
            st.subheader(f"Avg cost per trial (USD){eff_note}")
            fig_cost = px.bar(eff_rows, x="group", y="avg_cost_usd", hover_data=["cost_usd", "total"])
            fig_cost.update_xaxes(title=" | ".join(group_by))
            st.plotly_chart(fig_cost, use_container_width=True)

        if eff_rows:
            st.subheader(f"Avg duration per trial (s){eff_note}")
            duration_rows = []
            for r in eff_rows:
                duration_rows.append({"group": r["group"], "phase": "env setup", "seconds": r["avg_env_setup_s"]})
                duration_rows.append({"group": r["group"], "phase": "agent setup", "seconds": r["avg_agent_setup_s"]})
                duration_rows.append({"group": r["group"], "phase": "agent exec", "seconds": r["avg_agent_exec_s"]})
                duration_rows.append({"group": r["group"], "phase": "verifier", "seconds": r["avg_verifier_s"]})
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

            st.subheader(f"Avg token usage per trial{eff_note}")
            # n_input_tokens includes cache; uncached = input - cache. See harbor/viewer/server.py:_uncached_input.
            token_rows = []
            for r in eff_rows:
                n_in = r["avg_input_tokens"] or 0
                n_cache = r["avg_cache_tokens"] or 0
                n_out = r["avg_output_tokens"] or 0
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

def _trial_row(t: dict) -> dict:
    row = {
        "trial": t["trial"],
        "job": t["job"],
        "task": t.get("task") or "?",
        "integration": t["integration"],
        "integration_type": t["integration_type"],
        "model": t["model"],
        "tests_passed": t["tests_passed"],
        "failed_criteria": t["failed_criteria"],
        "errored": t["errored"],
        "exception": t["exception"],
        "escape_calls_detail": " | ".join(t["escape_call_values"]),
        "errored_calls_detail": " | ".join(t["errored_call_values"]),
        "agent_turns": t["agent_turns"],
        "tool_calls": t["tool_calls_total"],
        "channel_calls": t["channel_calls"],
        "off_channel_calls": t["off_channel_calls"],
        "errored_calls": t["errored_calls"],
        "channel_output_chars": t["channel_output_chars"],
        "prompt_baseline_tokens": t["prompt_baseline_tokens"],
        "input_tokens": t["n_input"],
        "cache_tokens": t["n_cache"],
        "output_tokens": t["n_output"],
        "cost_usd": t["cost_usd"],
        "agent_exec_s": t["t_agent_exec"],
    }
    return row


with tab_trials:
    if not trials:
        st.info("No trials in the selected jobs.")
    else:
        # Trial picker: every trial across selected jobs. Pick rows to narrow the
        # plot below; empty selection = show all.
        overview_rows = [_trial_row(t) for t in trials]
        ov_event = st.dataframe(
            overview_rows,
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row",
            use_container_width=True,
            key="trial_overview",
        )
        picked_idx = ov_event.selection.rows if ov_event and ov_event.selection.rows else None
        picked_trials = [trials[i] for i in picked_idx] if picked_idx else list(trials)

        x_axis = st.selectbox("X axis", ["time (s)", "step", "trial"], index=0)
        only_channel = st.checkbox("Show only channel events", value=False)
        # Style: color = integration_type, dash = (model, agent). Trials sharing all
        # three render identically (intentional). Each distinct (integration_type,
        # model, agent) combination contributes a single legend entry.
        palette = px.colors.qualitative.Plotly
        dash_cycle = ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"]
        modes_seen = sorted({t["integration_type"] for t in picked_trials})
        ma_seen = sorted({(t.get("model") or "?", t.get("agent") or "?") for t in picked_trials})
        color_for = {v: palette[i % len(palette)] for i, v in enumerate(modes_seen)}
        dash_for = {ma: dash_cycle[i % len(dash_cycle)] for i, ma in enumerate(ma_seen)}
        fig_tl = go.Figure()
        tool_call_rows = []
        for trial_idx, t in enumerate(picked_trials, start=1):
            tl = load_trial_timeline(t["job"], t["trial"], mtimes.get(t["job"], 0.0))
            verdict = "pass" if t["tests_passed"] else ("error" if t["errored"] else "fail")
            hover_label = f"{t['trial']} · {verdict}<br>{t['job']}"
            kinds = [
                metrics_mod.classify_call(
                    {"function_name": m["name"], "arguments": m["args"]},
                    t["integration_target"], t["channel"],
                )
                for m in tl["marks"]
            ]
            channel_flags = [k == "channel" for k in kinds]
            for m, kind in zip(tl["marks"], kinds):
                tool_call_rows.append({
                    "trial": t["trial"],
                    "integration_type": t["integration_type"],
                    "t_s": round(m["t"], 2),
                    "cum_tokens": m["cum_tokens"],
                    "tool": m["name"],
                    "args": json.dumps(m["args"])[:300],
                    "kind": kind,
                })
            if not tl["line"]:
                continue
            mode = t["integration_type"]
            ma = (t.get("model") or "?", t.get("agent") or "?")
            color = color_for[mode]
            dash = dash_for[ma]
            # One legend entry per trial: name carries the trial id + style context
            # so users can tell trials apart even when several share color/dash.
            trace_name = f"{t['trial']} · {mode} · {ma[1]} · {ma[0]}"
            trace_group = f"{t['job']}/{t['trial']}"

            def _x(r):
                if x_axis == "step":
                    return r.get("step")
                if x_axis == "trial":
                    return t["trial"]
                return r["t"]

            line_shown = x_axis != "trial"
            if line_shown:
                fig_tl.add_trace(go.Scatter(
                    x=[_x(r) for r in tl["line"]],
                    y=[r["cum_tokens"] for r in tl["line"]],
                    mode="lines",
                    name=trace_name,
                    legendgroup=trace_group,
                    showlegend=True,
                    line=dict(color=color, dash=dash),
                    hovertemplate="%{x}<br>%{y} tokens<extra>" + hover_label + "</extra>",
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
                    name=trace_name,
                    legendgroup=trace_group,
                    # If the line trace already carries the legend entry for this
                    # trial, suppress the markers' duplicate entry.
                    showlegend=not line_shown,
                    marker=dict(size=8, symbol="circle", color=color),
                    customdata=[[m["name"], json.dumps(m["args"])[:300]] for m, _ in visible_marks],
                    hovertemplate="%{x}<br>%{y} tokens<br><b>%{customdata[0]}</b><br>%{customdata[1]}<extra>" + hover_label + "</extra>",
                ))
        if not fig_tl.data:
            st.info("No trajectory.json found for the picked trials.")
        else:
            fig_tl.update_xaxes(title=x_axis)
            fig_tl.update_yaxes(title="cumulative tokens")
            st.plotly_chart(fig_tl, use_container_width=True)
        st.subheader("Trial details")

        def _stacked_bar(segments: list[dict], total_label: str) -> go.Figure:
            fig = go.Figure()
            for s in segments:
                if (s["value"] or 0) <= 0:
                    continue
                fig.add_trace(go.Bar(
                    y=[""], x=[s["value"]], name=s["label"],
                    marker_color=s["color"], orientation="h",
                    hovertemplate=f"{s['label']}: %{{x:,.2f}}<extra></extra>",
                ))
            fig.update_layout(
                barmode="stack",
                height=130,
                margin=dict(l=8, r=8, t=28, b=8),
                title=dict(text=total_label, x=0, font=dict(size=12)),
                legend=dict(orientation="h", y=-0.3),
                xaxis=dict(showgrid=False, zeroline=False),
                yaxis=dict(visible=False),
            )
            return fig

        def _kv_row(label: str, value) -> dict:
            return {"metric": label, "value": "" if value is None else value}

        def _fmt_dt(dt) -> str:
            return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""

        def _render_trial_details(t: dict) -> None:
            verdict = "pass" if t["tests_passed"] else ("error" if t["errored"] else "fail")
            agent = t.get("agent") or "?"
            model = t.get("model") or "?"
            integration = t.get("integration") or "?"
            task = t.get("task") or "?"
            trial_path = t.get("trial_uri") or str(JOBS_DIR / t["job"] / t["trial"])
            if trial_path.startswith("file://"):
                trial_path = trial_path[7:]

            cached = t["n_cache"] or 0
            input_tot = t["n_input"] or 0
            uncached = max(0, input_tot - cached)
            output = t["n_output"] or 0
            total_toks = input_tot + output
            phase_s = t["t_env_setup"] + t["t_agent_setup"] + t["t_agent_exec"] + t["t_verifier"]

            source_seg = t.get("source") or "_"
            agent_seg = t.get("agent") or "_"
            provider_seg = t.get("model_provider") or "_"
            model_seg = t.get("model_name_short") or t.get("model") or "_"
            harbor_url = (
                f"{harbor_view_base}/jobs/{quote(t['job'], safe='')}/tasks/"
                f"{quote(source_seg, safe='')}/{quote(agent_seg, safe='')}/"
                f"{quote(provider_seg, safe='')}/{quote(model_seg, safe='')}/"
                f"{quote(t.get('task') or '_', safe='')}/trials/"
                f"{quote(t['trial'], safe='')}"
            )
            header_lines = [
                f"**Trial:** `{t['trial']}`",
                f"**Job:** `{t['job']}`",
                f"**Task:** `{task}`",
                f"**Integration:** `{integration}`",
                f"**Agent:** {agent}",
                f"**Model:** {model}",
                f"**Verdict:** {verdict}",
                f"**Path:** `{trial_path}`",
                f'**Harbor view:** <a href="{harbor_url}" target="_blank" rel="noopener">open in new tab</a>',
            ]
            st.markdown("  \n".join(header_lines), unsafe_allow_html=True)

            st.plotly_chart(
                _stacked_bar(
                    [
                        {"label": "cached", "value": cached, "color": "#9ca3af"},
                        {"label": "uncached", "value": uncached, "color": "#6b7280"},
                        {"label": "output", "value": output, "color": "#374151"},
                    ],
                    f"Tokens · {total_toks:,}",
                ),
                use_container_width=True,
            )
            st.plotly_chart(
                _stacked_bar(
                    [
                        {"label": "env setup", "value": t["t_env_setup"], "color": "#9ca3af"},
                        {"label": "agent setup", "value": t["t_agent_setup"], "color": "#6b7280"},
                        {"label": "agent exec", "value": t["t_agent_exec"], "color": "#4b5563"},
                        {"label": "verifier", "value": t["t_verifier"], "color": "#374151"},
                    ],
                    f"Timing · {phase_s:.1f}s",
                ),
                use_container_width=True,
            )

            tab_calls, tab_traj, tab_info = st.tabs(["Tool calls", "Trajectory", "Details"])

            with tab_calls:
                filtered = [
                    {"t_s": r["t_s"], "kind": r["kind"], "tool": r["tool"],
                     "args": r["args"], "cum_tokens": r["cum_tokens"]}
                    for r in tool_call_rows
                    if r["trial"] == t["trial"] and (not only_channel or r["kind"] == "channel")
                ]
                st.caption(f"{len(filtered)} call(s)")
                if filtered:
                    st.dataframe(filtered, use_container_width=True)
                else:
                    st.info("No tool calls recorded.")

            with tab_traj:
                tl = load_trial_timeline(t["job"], t["trial"], mtimes.get(t["job"], 0.0))
                if not tl["line"]:
                    st.info("No trajectory.json found for this trial.")
                else:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=[r["t"] for r in tl["line"]],
                        y=[r["cum_tokens"] for r in tl["line"]],
                        mode="lines",
                        name="cumulative tokens",
                        line=dict(color="#4b5563"),
                        hovertemplate="%{x:.1f}s<br>%{y:,} tokens<extra></extra>",
                    ))
                    kinds = [
                        metrics_mod.classify_call(
                            {"function_name": m["name"], "arguments": m["args"]},
                            t["integration_target"], t["channel"],
                        )
                        for m in tl["marks"]
                    ]
                    if tl["marks"]:
                        fig.add_trace(go.Scatter(
                            x=[m["t"] for m in tl["marks"]],
                            y=[m["cum_tokens"] for m in tl["marks"]],
                            mode="markers",
                            name="tool calls",
                            marker=dict(
                                size=9,
                                color=["#10b981" if k == "channel" else "#f59e0b" for k in kinds],
                                line=dict(color="#111827", width=0.5),
                            ),
                            customdata=[[m["name"], json.dumps(m["args"])[:300], k]
                                        for m, k in zip(tl["marks"], kinds)],
                            hovertemplate=("%{x:.1f}s<br>%{y:,} tokens<br>"
                                           "<b>%{customdata[0]}</b> (%{customdata[2]})<br>"
                                           "%{customdata[1]}<extra></extra>"),
                        ))
                    fig.update_xaxes(title="seconds")
                    fig.update_yaxes(title="cumulative tokens")
                    fig.update_layout(height=360, margin=dict(l=8, r=8, t=24, b=8))
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption(f"{tl['n_steps']} step(s) · {tl['n_tool_calls']} tool call(s)")

            with tab_info:
                if t["exception"]:
                    st.error(f"Exception: {t['exception']}")
                if t["failed_criteria"]:
                    st.warning(f"Failed criteria: {t['failed_criteria']}")
                if t["escape_call_values"]:
                    st.caption("Off-channel calls: " + " | ".join(t["escape_call_values"]))
                if t["errored_call_values"]:
                    st.caption("Errored calls: " + " | ".join(t["errored_call_values"]))

                duration_s = None
                if t["started_at"] and t["finished_at"]:
                    duration_s = (t["finished_at"] - t["started_at"]).total_seconds()
                cache_rate = (cached / input_tot) if input_tot else None

                kv = [
                    _kv_row("verdict", verdict),
                    _kv_row("reward", "" if t.get("reward") is None else f"{t['reward']:.2f}"),
                    _kv_row("cost ($)", f"{t['cost_usd']:.4f}"),
                    _kv_row("started_at", _fmt_dt(t["started_at"])),
                    _kv_row("finished_at", _fmt_dt(t["finished_at"])),
                    _kv_row("duration (s)", "" if duration_s is None else f"{duration_s:.1f}"),
                    _kv_row("env setup (s)", f"{t['t_env_setup']:.1f}"),
                    _kv_row("agent setup (s)", f"{t['t_agent_setup']:.1f}"),
                    _kv_row("agent exec (s)", f"{t['t_agent_exec']:.1f}"),
                    _kv_row("verifier (s)", f"{t['t_verifier']:.1f}"),
                    _kv_row("input tokens", f"{input_tot:,}"),
                    _kv_row("cached tokens", f"{cached:,}"),
                    _kv_row("uncached input tokens", f"{uncached:,}"),
                    _kv_row("output tokens", f"{output:,}"),
                    _kv_row("cache hit rate", "" if cache_rate is None else f"{cache_rate:.1%}"),
                    _kv_row("prompt baseline tokens",
                            "" if t["prompt_baseline_tokens"] in (None, 0) else f"{t['prompt_baseline_tokens']:,}"),
                    _kv_row("agent turns", t["agent_turns"]),
                    _kv_row("tool calls (total)", t["tool_calls_total"]),
                    _kv_row("channel calls", t["channel_calls"]),
                    _kv_row("off-channel calls", t["off_channel_calls"]),
                    _kv_row("errored calls", t["errored_calls"]),
                    _kv_row("channel output chars", f"{t['channel_output_chars']:,}"),
                ]
                st.dataframe(kv, hide_index=True, use_container_width=True, height=min(36 + 35 * len(kv), 600))

        if not picked_trials:
            st.info("Pick at least one trial above.")
        else:
            trial_options = [t["trial"] for t in picked_trials]
            by_name = {t["trial"]: t for t in picked_trials}
            name = st.segmented_control(
                "Inspect", trial_options, selection_mode="single", default=trial_options[0]
            )
            if name:
                _render_trial_details(by_name[name])

with tab_grid:
    # Per (task, agent+model, integration_type) avg-tokens stacked bars, faceted by row=task, col=agent+model.
    grid_trials = [t for t in trials if t["tests_passed"]] if passed_only else trials
    cells: dict[tuple, dict] = defaultdict(lambda: {"n_input": 0, "n_cache": 0, "n_output": 0, "count": 0})
    for t in grid_trials:
        am = f"{t.get('agent') or '?'} / {t.get('model') or '?'}"
        key = (t["task"], am, t["integration_type"])
        c = cells[key]
        c["n_input"] += t["n_input"]
        c["n_cache"] += t["n_cache"]
        c["n_output"] += t["n_output"]
        c["count"] += 1
    grid_rows = []
    for (task, am, mode), c in cells.items():
        n = c["count"] or 1
        grid_rows.append({"task": task, "agent_model": am, "integration_type": mode,
                          "kind": "input (cached)", "tokens": c["n_cache"] / n})
        grid_rows.append({"task": task, "agent_model": am, "integration_type": mode,
                          "kind": "input (uncached)", "tokens": max(0, c["n_input"] - c["n_cache"]) / n})
        grid_rows.append({"task": task, "agent_model": am, "integration_type": mode,
                          "kind": "output", "tokens": c["n_output"] / n})
    if not grid_rows:
        st.info("No trial data in the selected jobs (with 'passed trials only' on, only passed trials count).")
    else:
        mode_order = sorted({r["integration_type"] for r in grid_rows})
        fig_grid = px.bar(
            grid_rows,
            x="integration_type",
            y="tokens",
            color="kind",
            facet_col="agent_model",
            facet_row="task",
            barmode="stack",
            category_orders={
                "kind": ["input (cached)", "input (uncached)", "output"],
                "integration_type": mode_order,
            },
            color_discrete_map={
                "input (cached)": "#9ecae1",
                "input (uncached)": "#d62728",
                "output": "#2ca02c",
            },
        )
        # Facet titles default to "task=...", strip the prefix.
        fig_grid.for_each_annotation(lambda a: a.update(text=a.text.split("=", 1)[-1]))
        n_tasks = len({r["task"] for r in grid_rows})
        fig_grid.update_layout(height=max(300, 260 * n_tasks))
        st.plotly_chart(fig_grid, use_container_width=True)
