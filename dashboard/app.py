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

REPO_ROOT = Path(__file__).resolve().parents[1]
# Set by `mcp-evals dashboard` so external projects can point at their own jobs dir.
JOBS_DIR = Path(os.environ.get("MCP_EVALS_JOBS_DIR", REPO_ROOT / "jobs")).expanduser().resolve()
# Fallback parse for jobs predating MCP_EVALS_CONNECTOR in verifier env.
KNOWN_CONNECTORS = {"mcp", "cli", "skill", "mcpc"}
GROUP_KEYS = ["trial", "job", "apps", "connector", "task", "agent", "model"]

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
    section[data-testid="stSidebar"][aria-expanded="true"] { width: 420px !important; min-width: 420px !important; }
    section[data-testid="stSidebar"][aria-expanded="false"] { min-width: 0 !important; width: 0 !important; }
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


def job_mtime(job_dir: Path) -> float:
    # Cache-invalidation signature for a job. The job dir's own mtime only tracks
    # when trial *subdirs* are created (all up front), not when each trial's
    # result.json lands inside an already-existing subdir. A slow trial (e.g. a
    # 300s timeout) finishes long after the dir was made, so keying caches on the
    # job dir mtime alone leaves that trial invisible until a full restart. Taking
    # the max over the immediate children picks up each completion (a trial's
    # subdir mtime bumps when result.json is written into it).
    try:
        mtimes = [job_dir.stat().st_mtime]
        mtimes += [c.stat().st_mtime for c in job_dir.iterdir()]
        return max(mtimes)
    except OSError:
        return 0.0


def _fallback_connector(job_name: str) -> str:
    # Used only when the trial's verifier env lacks MCP_EVALS_CONNECTOR.
    # Naming convention (AGENTS.md): <dataset>-<harness>-<model>-<connector>-<purpose>.
    for tok in job_name.split("-"):
        if tok in KNOWN_CONNECTORS:
            return tok
    return "?"


# Per-token list prices in USD. cache_write_5m only set where the harness
# reports cache_creation_input_tokens (claude trajectories' metrics.extra);
# others fall back to input rate. We register the same rates under every slug
# variant we see in the wild (trial config vs trajectory.json sometimes order
# version/family differently, e.g. `claude-sonnet-4.6` vs `claude-4.6-sonnet`).
# TODO: replace the alias soup with a single canonical key per model and a
# normalize step in _pricing_for, or always look up using the trajectory's
# `agent.model_name` (provider-canonical, includes snapshot date) instead of
# the config slug. See docs/todo.md "Model pricing key lookup".
_CLAUDE_SONNET_46 = {
    # https://platform.claude.com/docs/en/about-claude/pricing (Claude Sonnet 4.6 row).
    "input": 3.0e-6, "cache_read": 0.30e-6, "cache_write_5m": 3.75e-6, "output": 15.0e-6,
}
_MODEL_PRICES: dict[str, dict] = {
    "anthropic/claude-4.6-sonnet": _CLAUDE_SONNET_46,
    "anthropic/claude-sonnet-4.6": _CLAUDE_SONNET_46,
    # https://api-docs.deepseek.com/quick_start/pricing
    "openrouter/deepseek/deepseek-v4-pro": {
        "input": 0.435e-6, "cache_read": 0.003625e-6, "output": 0.87e-6,
    },
    # https://developers.openai.com/api/docs/pricing (gpt-5.4 row).
    # Codex config uses `openai/gpt-5.4`; trajectory writes bare `gpt-5.4`.
    "gpt-5.4": {
        "input": 2.50e-6, "cache_read": 0.25e-6, "output": 15.0e-6,
    },
    "openai/gpt-5.4": {
        "input": 2.50e-6, "cache_read": 0.25e-6, "output": 15.0e-6,
    },
}


def _pricing_for(model_name: str | None) -> dict | None:
    if not model_name:
        return None
    # Strip OpenRouter @preset/... routing suffix and any trailing -YYYYMMDD
    # release-date stamp (e.g. anthropic/claude-4.6-sonnet-20260217).
    base = model_name.split("@", 1)[0]
    import re
    base = re.sub(r"-\d{8}$", "", base)
    return _MODEL_PRICES.get(base) or _MODEL_PRICES.get(model_name)


def _step_cost(metrics: dict, pricing: dict) -> float:
    prompt = metrics.get("prompt_tokens") or 0
    cached = metrics.get("cached_tokens") or 0
    completion = metrics.get("completion_tokens") or 0
    # Claude trajectories expose cache_creation_input_tokens via metrics.extra;
    # priced at the 1.25x write rate when known, else folded into uncached input.
    cache_write = ((metrics.get("extra") or {}).get("cache_creation_input_tokens")) or 0
    uncached = max(0, prompt - cached - cache_write)
    write_rate = pricing.get("cache_write_5m") or pricing["input"]
    return (
        uncached * pricing["input"]
        + cached * pricing["cache_read"]
        + cache_write * write_rate
        + completion * pricing["output"]
    )


@st.cache_data(show_spinner=False)
def load_trial_timeline(
    job_name: str, trial_name: str, mtime: float, model_name: str | None = None
) -> dict:
    # Reads agent/trajectory.json and returns:
    #   line:   [{t, cum_tokens, cum_cost_raw}] one point per step
    #   marks:  [{t, cum_tokens, cum_cost_raw, name, args}] one point per tool call
    #   n_steps, n_tool_calls, est_cost_total
    # `t` is seconds from the trial's first step. cum_cost_raw is the
    # pricing-table estimate; rescale to Harbor's trial cost_usd at render time.
    del mtime
    traj_path = JOBS_DIR / job_name / trial_name / "agent" / "trajectory.json"
    empty = {"line": [], "marks": [], "n_steps": 0, "n_tool_calls": 0, "est_cost_total": 0.0}
    if not traj_path.exists():
        return empty
    try:
        steps = json.loads(traj_path.read_text()).get("steps", [])
    except (json.JSONDecodeError, OSError):
        return empty
    pricing = _pricing_for(model_name)
    line: list[dict] = []
    marks: list[dict] = []
    t0: datetime | None = None
    cum_tokens = 0
    cum_cost = 0.0
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
        cum_tokens += (m.get("prompt_tokens") or 0) + (m.get("completion_tokens") or 0)
        if pricing:
            cum_cost += _step_cost(m, pricing)
        line.append({"t": t, "step": step_id, "cum_tokens": cum_tokens, "cum_cost_raw": cum_cost})
        for tc in (s.get("tool_calls") or []):
            marks.append({
                "t": t,
                "step": step_id,
                "cum_tokens": cum_tokens,
                "cum_cost_raw": cum_cost,
                "name": tc.get("function_name") or "?",
                "args": tc.get("arguments") or {},
            })
    return {
        "line": line,
        "marks": marks,
        "n_steps": len(steps),
        "n_tool_calls": len(marks),
        "est_cost_total": cum_cost,
    }


def _normalize_content(content) -> str:
    # Flatten message/observation content (str | list[ContentPart] | None) to text.
    # ContentPart: {"type": "text"|"image", "text"?: str, "source"?: {"path": ...}}
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if not isinstance(p, dict):
                parts.append(str(p))
                continue
            if p.get("type") == "text":
                parts.append(p.get("text") or "")
            elif p.get("type") == "image":
                path = (p.get("source") or {}).get("path") or "?"
                parts.append(f"_[image: `{path}`]_")
            else:
                parts.append(json.dumps(p))
        return "\n".join(parts)
    return str(content)


def _first_line(text: str, limit: int = 120) -> str:
    lines = (text or "").strip().splitlines()
    line = lines[0] if lines else ""
    return line[:limit] + ("…" if len(line) > limit else "")


def _fmt_secs(s: float | None) -> str:
    if s is None:
        return ""
    if s < 60:
        return f"{s:.1f}s"
    m, rem = divmod(s, 60)
    return f"{int(m)}m {rem:.0f}s"


@st.cache_data(show_spinner=False)
def load_trial_steps(
    job_name: str, trial_name: str, mtime: float, model_name: str | None = None
) -> list[dict]:
    # Mirrors what `harbor view jobs` renders per step: source, model, message,
    # reasoning, tool calls, observations, per-step metrics, and timing offsets.
    del mtime
    traj_path = JOBS_DIR / job_name / trial_name / "agent" / "trajectory.json"
    if not traj_path.exists():
        return []
    try:
        steps = json.loads(traj_path.read_text()).get("steps", [])
    except (json.JSONDecodeError, OSError):
        return []
    pricing = _pricing_for(model_name)
    t0: datetime | None = None
    prev_t: float | None = None
    cum_billed = 0
    cum_cost_raw = 0.0
    out: list[dict] = []
    for s in steps:
        ts = s.get("timestamp")
        when: datetime | None = None
        if ts:
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                when = None
        if when is not None and t0 is None:
            t0 = when
        t_offset = (when - t0).total_seconds() if (when and t0) else None
        t_delta = (t_offset - prev_t) if (t_offset is not None and prev_t is not None) else None
        if t_offset is not None:
            prev_t = t_offset
        m = s.get("metrics") or {}
        prompt = m.get("prompt_tokens")
        cached = m.get("cached_tokens")
        completion = m.get("completion_tokens")
        # Codex trajectories omit cached_tokens — leave uncached as the full prompt.
        uncached = (prompt - cached) if (prompt is not None and cached is not None) else prompt
        cum_billed += (prompt or 0) + (completion or 0)
        step_cost_raw = _step_cost(m, pricing) if (pricing and (prompt or completion)) else None
        if step_cost_raw is not None:
            cum_cost_raw += step_cost_raw
        out.append({
            "step_id": s.get("step_id"),
            "source": s.get("source") or "?",
            "model_name": s.get("model_name"),
            "message": s.get("message"),
            "reasoning": s.get("reasoning_content"),
            "tool_calls": s.get("tool_calls") or [],
            "observation": (s.get("observation") or {}).get("results") or [],
            "metrics": m,
            "cached": cached,
            "uncached": uncached,
            "output": completion,
            "cum_billed": cum_billed if (prompt is not None or completion is not None) else None,
            "step_cost_raw": step_cost_raw,
            "cum_cost_raw": cum_cost_raw if step_cost_raw is not None else None,
            "t_offset": t_offset,
            "t_delta": t_delta,
        })
    return out


_SOURCE_COLORS = {
    "system": "#6b7280",
    "user":   "#2563eb",
    "agent":  "#7c3aed",
}


def _fmt_n(n: int | float | None) -> str:
    if n is None:
        return "-"
    if n < 1000:
        return str(int(n))
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


_KIND_COLORS = {"connector": "#10b981", "escape": "#f59e0b"}


@st.dialog("Step detail", width="large")
def _show_step_dialog(step: dict, kinds: list[str]) -> None:
    color = _SOURCE_COLORS.get(step["source"], "#6b7280")
    header = (
        f'<span style="display:inline-block;padding:1px 8px;'
        f'border-radius:4px;background:{color};color:white;'
        f'font-size:11px;font-weight:600;">{step["source"]}</span> '
        f'<span style="color:#6b7280;font-size:12px;">step #{step["step_id"]}'
    )
    if step["model_name"]:
        header += f' · {step["model_name"]}'
    header += "</span>"
    st.markdown(header, unsafe_allow_html=True)

    message_text = _normalize_content(step["message"])
    if message_text:
        st.markdown(message_text)

    if step["reasoning"]:
        with st.expander("Reasoning", expanded=False):
            st.code(step["reasoning"], language=None)

    for tc, kind in zip(step["tool_calls"], kinds):
        fname = tc.get("function_name") or "?"
        args = tc.get("arguments") or {}
        kc = _KIND_COLORS.get(kind, "#6b7280")
        st.markdown(
            f'<div style="margin-top:8px;">tool call · <code>{fname}</code> '
            f'<span style="display:inline-block;padding:1px 6px;'
            f'border-radius:4px;background:{kc};color:white;'
            f'font-size:10px;font-weight:600;">{kind}</span></div>',
            unsafe_allow_html=True,
        )
        st.code(json.dumps(args, indent=2), language="json")

    for i, r in enumerate(step["observation"]):
        content = _normalize_content(r.get("content"))
        if not content:
            continue
        st.caption(f"observation #{i + 1}")
        st.code(content, language=None)

    cost = (step["metrics"] or {}).get("cost_usd")
    if cost is not None:
        st.caption(f"${cost:.4f}")


def _render_trajectory_steps(
    steps: list[dict],
    connectors_by_app: dict[str, str],
    state_key: str,
    trial_cost_usd: float | None = None,
) -> None:
    if not steps:
        st.info("No trajectory.json found for this trial.")
        return

    # Classify each step's tool calls so the table and dialog agree on what
    # counts as connector / escape. Same call as the Tool calls tab uses.
    step_kinds: list[list[str]] = []
    for s in steps:
        step_kinds.append([
            metrics_mod.classify_call_multi(
                {"function_name": tc.get("function_name") or "?", "arguments": tc.get("arguments") or {}},
                connectors_by_app,
            )
            for tc in s["tool_calls"]
        ])

    # Rescale per-step raw cost so the column matches Harbor's trial total. If
    # we have no actual cost (opencode) or no per-step pricing data, factor=1.
    final_raw = next((s["cum_cost_raw"] for s in reversed(steps) if s["cum_cost_raw"] is not None), 0.0)
    scale = (trial_cost_usd / final_raw) if (trial_cost_usd and final_raw > 0) else 1.0

    rows = []
    for s, kinds in zip(steps, step_kinds):
        preview = _first_line(_normalize_content(s["message"]))
        kind_label = ",".join(sorted(set(kinds))) if kinds else ""
        prompt = (s["metrics"] or {}).get("prompt_tokens")
        cache_rate = (s["cached"] / prompt) if (s["cached"] is not None and prompt) else None
        step_cost = s["step_cost_raw"] * scale if s["step_cost_raw"] is not None else None
        cum_cost = s["cum_cost_raw"] * scale if s["cum_cost_raw"] is not None else None
        rows.append({
            "#": s["step_id"],
            "source": s["source"],
            "model": s["model_name"] or "",
            "+Δs": _fmt_secs(s["t_delta"]) if s["t_delta"] is not None else "",
            "Σs": _fmt_secs(s["t_offset"]) if s["t_offset"] is not None else "",
            "cached": _fmt_n(s["cached"]),
            "uncached": _fmt_n(s["uncached"]),
            "cache%": "" if cache_rate is None else f"{cache_rate:.0%}",
            "out": _fmt_n(s["output"]),
            "Σ tok": _fmt_n(s["cum_billed"]),
            "$": "" if step_cost is None else f"{step_cost:.4f}",
            "Σ $": "" if cum_cost is None else f"{cum_cost:.4f}",
            "kind": kind_label,
            "preview": preview,
        })

    event = st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        height=min(36 + 35 * len(rows), 600),
        on_select="rerun",
        selection_mode="single-row",
        key=f"traj_df_{state_key}",
    )

    # Open the dialog only when the selection changes — otherwise dismissing the
    # dialog would re-open it on the next rerun because the row stays selected.
    seen_key = f"traj_shown_{state_key}"
    if event.selection.rows:
        idx = event.selection.rows[0]
        if st.session_state.get(seen_key) != idx:
            st.session_state[seen_key] = idx
            _show_step_dialog(steps[idx], step_kinds[idx])
    else:
        st.session_state.pop(seen_key, None)


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
        connectors_by_app: dict[str, str] = {}
        if tr.config and tr.config.verifier:
            connectors_by_app = metrics_mod.parse_run_axes(tr.config.verifier.env)
        if not connectors_by_app:
            # Old jobs (pre connector/app split) only set EXPECTED_CONNECTOR or
            # encoded both axes in the job name. Best-effort recovery.
            legacy_connector = None
            if tr.config and tr.config.verifier:
                legacy_connector = tr.config.verifier.env.get("EXPECTED_CONNECTOR") or None
            legacy_connector = legacy_connector or _fallback_connector(job_name)
            fallback_app = metrics_mod.app_for_task(tr.task_name or "")
            if fallback_app and legacy_connector and legacy_connector != "?":
                connectors_by_app = {fallback_app: legacy_connector}
        app_keys = sorted(connectors_by_app)
        apps_str = ",".join(app_keys) or "?"
        connector_values = sorted(set(connectors_by_app.values()))
        connector_str = connector_values[0] if len(connector_values) == 1 else (
            "hybrid" if connector_values else "?"
        )
        trial_dir = JOBS_DIR / job_name / trial_name
        details = read_json(trial_dir / "verifier" / "reward-details.json")
        passed = metrics_mod.tests_passed(details)
        traj = read_json(trial_dir / "agent" / "trajectory.json") or {}
        trial_metrics, per_call = metrics_mod.compute_trial_metrics(traj, connectors_by_app)
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
            "apps": apps_str,
            "connector": connector_str,
            "connectors_by_app": connectors_by_app,
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
            "subagent_tokens": metrics_mod.sum_subagent_tokens(trial_dir),
            **trial_metrics,
        })
    return out


def aggregate(trials: list[dict], by: list[str]) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {
        "passed": 0, "errored": 0, "total": 0,
        "cost_usd": 0.0, "n_input": 0, "n_cache": 0, "n_output": 0,
        "t_env_setup": 0.0, "t_agent_setup": 0.0, "t_agent_exec": 0.0, "t_verifier": 0.0,
        "agent_turns": 0, "connector_calls": 0, "off_connector_calls": 0,
        "errored_calls": 0, "connector_output_chars": 0,
        "subagent_tokens": 0,
        "baseline_sum": 0, "baseline_n": 0,
        "reward_sum": 0.0, "reward_n": 0,
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
        g["connector_calls"] += t["connector_calls"]
        g["off_connector_calls"] += t["off_connector_calls"]
        g["errored_calls"] += t["errored_calls"]
        g["connector_output_chars"] += t["connector_output_chars"]
        g["subagent_tokens"] += t["subagent_tokens"]
        if t["prompt_baseline_tokens"]:
            g["baseline_sum"] += t["prompt_baseline_tokens"]
            g["baseline_n"] += 1
        if t.get("reward") is not None:
            g["reward_sum"] += t["reward"]
            g["reward_n"] += 1
    rows = []
    for key, g in groups.items():
        total = g["total"] or 1
        rows.append({
            "group": key,
            "total": g["total"],
            "passed": g["passed"],
            "errored": g["errored"],
            "pass_rate": g["passed"] / total,
            # None when no trial had a numeric reward (verifier returned no rewards dict).
            "avg_reward": (g["reward_sum"] / g["reward_n"]) if g["reward_n"] else None,
            "avg_agent_turns": g["agent_turns"] / total,
            "avg_connector_calls": g["connector_calls"] / total,
            "avg_off_connector_calls": g["off_connector_calls"] / total,
            "avg_errored_calls": g["errored_calls"] / total,
            "avg_connector_output_chars": g["connector_output_chars"] / total,
            "avg_subagent_tokens": g["subagent_tokens"] / total,
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
            "total_tokens": g["n_input"] + g["n_output"],
            "avg_input_tokens": g["n_input"] / total,
            "avg_cache_tokens": g["n_cache"] / total,
            "avg_uncached_input_tokens": max(0, g["n_input"] - g["n_cache"]) / total,
            "avg_output_tokens": g["n_output"] / total,
            "avg_total_tokens": (g["n_input"] + g["n_output"]) / total,
            # Parent trajectory + claude-code subagent transcripts; equals
            # avg_total_tokens for codex/opencode (no subagents).
            "avg_total_tokens_inc_subagents": (g["n_input"] + g["n_output"] + g["subagent_tokens"]) / total,
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
        key=job_mtime,
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


job_mtimes = {d.name: job_mtime(d) for d in job_dirs}
trial_counts = {j: _job_trial_count(j, job_mtimes[j]) for j in all_jobs}
default_jobs = set(all_jobs[:5])

# Non-filter controls first: these change how metrics are computed / linked, not
# which trials are in scope.
st.sidebar.markdown("**Settings**")
harbor_view_base = st.sidebar.text_input(
    "Harbor view base URL", value="http://127.0.0.1:8080",
    help="Base URL of `harbor view jobs`. Used to link trials to their detail page.",
).rstrip("/")

# Jobs is the first filter: it gates which trials get loaded; the dimension
# filters below (connector / agent+model / task) then narrow what was loaded.
st.sidebar.markdown("**Filters**")
# Efficiency of a failed trial is noise, so 'Passed' is the usual comparison set;
# 'Not passed' isolates failures. Applied globally so every tab sees the same set.
pass_filter = st.sidebar.segmented_control(
    "Trials", ["All", "Passed", "Not passed"], default="All", key="pass_filter",
)
# Errored trials have an exception; their metrics are usually unreliable noise.
errored_filter = st.sidebar.segmented_control(
    "Errored", ["All", "Errored", "Not errored"], default="All", key="errored_filter",
)
st.sidebar.caption("Jobs")
_b_all, _b_none = st.sidebar.columns(2)
if _b_all.button("All", key="jobs_all", use_container_width=True):
    for _j in all_jobs:
        st.session_state[f"job_cb_{_j}"] = True
if _b_none.button("None", key="jobs_none", use_container_width=True):
    for _j in all_jobs:
        st.session_state[f"job_cb_{_j}"] = False
with st.sidebar.container(height=240):
    selected = [
        j for j in all_jobs
        if st.checkbox(f"{j} ({trial_counts[j]})", value=j in default_jobs, key=f"job_cb_{j}")
    ]
selected = sorted(selected, key=all_jobs.index)
if not selected:
    st.info("Pick at least one job in the sidebar.")
    st.stop()

mtimes = {p.name: job_mtime(p) for p in job_dirs}
trials: list[dict] = []
for name in selected:
    trials.extend(load_trial_rows(name, mtimes.get(name, 0.0)))

if not trials:
    st.warning("Selected jobs have no trial results yet.")
    st.stop()

n_trials_total = len(trials)

# --- Sidebar dimension filters --------------------------------------------
# Narrow the loaded trials by dimension. Every value is selected by default;
# unticking narrows (untick down to one to isolate it). Options are derived from
# the trials in the currently selected jobs, so they track the job selection. The
# connector and agent+model chips always render (even with one value) for a
# consistent sidebar; high-cardinality Task is shown only when there's >1 value.
def _agent_model(t: dict) -> str:
    return f"{t.get('agent') or '?'} / {t.get('model') or '?'}"


_filters: list[tuple] = []

# Connector and agent+model are small fixed sets, so pills (toggle chips) read
# better than a dropdown. Task can be long and high-cardinality, so it stays a
# multiselect and sits last.
_chan_opts = sorted({t.get("connector") or "?" for t in trials})
_chosen = st.sidebar.pills(
    f"Connector ({len(_chan_opts)})", _chan_opts, selection_mode="multi",
    default=_chan_opts, key="filt_connector",
)
_filters.append((lambda t: t.get("connector") or "?", set(_chosen)))

_am_opts = sorted({_agent_model(t) for t in trials})
_chosen = st.sidebar.pills(
    f"Agent + model ({len(_am_opts)})", _am_opts, selection_mode="multi",
    default=_am_opts, key="filt_am",
)
_filters.append((_agent_model, set(_chosen)))

_task_opts = sorted({t.get("task") or "?" for t in trials})
if len(_task_opts) > 1:
    _chosen = st.sidebar.multiselect(
        f"Task ({len(_task_opts)})", _task_opts, default=_task_opts, key="filt_task"
    )
    _filters.append((lambda t: t.get("task") or "?", set(_chosen)))

trials = [t for t in trials if all(g(t) in chosen for g, chosen in _filters)]
if pass_filter == "Passed":
    trials = [t for t in trials if t["tests_passed"]]
elif pass_filter == "Not passed":
    trials = [t for t in trials if not t["tests_passed"]]
if errored_filter == "Errored":
    trials = [t for t in trials if t["errored"]]
elif errored_filter == "Not errored":
    trials = [t for t in trials if not t["errored"]]
if not trials:
    st.warning("No trials match the current filters. Loosen a filter in the sidebar "
               "(an empty selection excludes everything; the 'Trials' / 'Errored' "
               "toggles narrow to passed/failed/errored subsets).")
    st.stop()

tab_grouped, tab_trials, tab_grid, tab_matrix = st.tabs(["Grouped", "Trials", "Token grid", "Matrix"])

with tab_grouped:
    group_by = st.multiselect("Group by", GROUP_KEYS, default=["trial"])
    if not group_by:
        st.info("Pick at least one grouping dimension.")
    else:
        rows = aggregate(trials, group_by)
        st.caption(f"Showing {len(trials)} of {n_trials_total} trials.")

        st.subheader(f"Summary (grouped by {' | '.join(group_by)})")
        # Averages only: comparable across groups with different trial counts.
        # aggregate() still returns the sums (charts hover, other consumers);
        # cost_usd stays as the one total with natural sum semantics (job spend).
        SUMMARY_COLUMNS = [
            "group", "total", "passed", "errored", "pass_rate", "avg_reward",
            "avg_agent_turns", "avg_connector_calls", "avg_off_connector_calls",
            "avg_errored_calls", "avg_connector_output_chars", "avg_prompt_baseline_tokens",
            "avg_cost_usd", "avg_total_tokens", "avg_total_tokens_inc_subagents", "avg_subagent_tokens", "avg_uncached_input_tokens", "avg_cache_tokens", "cache_hit_rate", "avg_output_tokens",
            "avg_env_setup_s", "avg_agent_setup_s", "avg_agent_exec_s", "avg_verifier_s",
            "cost_usd",
        ]
        st.dataframe(
            [{k: r[k] for k in SUMMARY_COLUMNS} for r in rows],
            use_container_width=True,
        )

        # Pass rate and avg reward are trivial (1.0) once we restrict to passed
        # trials, so hide them when the filter is on.
        if pass_filter != "Passed":
            st.subheader("Pass rate")
            # All verifier criteria true and no trial exception. Health gate, not
            # an optimization target: anything under 1.0 deserves a look at the
            # trial.
            fig = px.bar(rows, x="group", y="pass_rate", hover_data=["passed", "errored", "total"])
            fig.update_xaxes(title=" | ".join(group_by))
            fig.update_yaxes(range=[0, 1])
            st.plotly_chart(fig, use_container_width=True)

            # Float reward from the verifier's rewards dict; captures partial
            # credit that pass_rate's all-or-nothing check throws away. None for
            # trials whose verifier emitted no numeric reward.
            reward_rows = [r for r in rows if r["avg_reward"] is not None]
            if reward_rows:
                st.subheader("Avg reward")
                fig_rw = px.bar(reward_rows, x="group", y="avg_reward", hover_data=["total"])
                fig_rw.update_xaxes(title=" | ".join(group_by))
                st.plotly_chart(fig_rw, use_container_width=True)

        st.subheader("Connector activity (avg per trial)")
        activity_rows = []
        for r in rows:
            activity_rows.append({"group": r["group"], "metric": "connector calls", "value": r["avg_connector_calls"]})
            activity_rows.append({"group": r["group"], "metric": "off-connector calls", "value": r["avg_off_connector_calls"]})
            activity_rows.append({"group": r["group"], "metric": "errored calls", "value": r["avg_errored_calls"]})
            activity_rows.append({"group": r["group"], "metric": "agent turns", "value": r["avg_agent_turns"]})
        if activity_rows:
            fig_act = px.bar(activity_rows, x="group", y="value", color="metric", barmode="group")
            fig_act.update_xaxes(title=" | ".join(group_by))
            st.plotly_chart(fig_act, use_container_width=True)

        st.subheader("Connector output size (avg chars per trial)")
        # Verbosity of the target surface: total tool-result chars of on-connector
        # calls. ~tokens = chars / 4. Caveat: opencode truncates huge bash
        # outputs in the trajectory, so cli numbers can undercount (see README
        # known limitations).
        output_rows = [
            {
                "group": r["group"],
                "chars": r["avg_connector_output_chars"],
                "est_tokens": int(r["avg_connector_output_chars"] / 4),
            }
            for r in rows
        ]
        if output_rows:
            fig_out = px.bar(output_rows, x="group", y="chars", hover_data=["est_tokens"])
            fig_out.update_xaxes(title=" | ".join(group_by))
            st.plotly_chart(fig_out, use_container_width=True)

        # The calls behind the off-connector / errored counts, plus failed tests
        # and trial exceptions.
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

        st.subheader("Avg cost per trial (USD)")
        fig_cost = px.bar(rows, x="group", y="avg_cost_usd", hover_data=["cost_usd", "total"])
        fig_cost.update_xaxes(title=" | ".join(group_by))
        st.plotly_chart(fig_cost, use_container_width=True)

        st.subheader("Avg duration per trial (s)")
        duration_rows = []
        for r in rows:
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

        st.subheader("Avg token usage per trial")
        # n_input_tokens includes cache; uncached = input - cache. See harbor/viewer/server.py:_uncached_input.
        token_rows = []
        for r in rows:
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
        "apps": t["apps"],
        "connector": t["connector"],
        "model": t["model"],
        "tests_passed": t["tests_passed"],
        "reward": t.get("reward"),
        "failed_criteria": t["failed_criteria"],
        "errored": t["errored"],
        "exception": t["exception"],
        "escape_calls_detail": " | ".join(t["escape_call_values"]),
        "errored_calls_detail": " | ".join(t["errored_call_values"]),
        "agent_turns": t["agent_turns"],
        "tool_calls": t["tool_calls_total"],
        "connector_calls": t["connector_calls"],
        "off_connector_calls": t["off_connector_calls"],
        "errored_calls": t["errored_calls"],
        "connector_output_chars": t["connector_output_chars"],
        "prompt_baseline_tokens": t["prompt_baseline_tokens"],
        "input_tokens": t["n_input"],
        "cache_tokens": t["n_cache"],
        "cache_hit_rate": (t["n_cache"] / t["n_input"]) if t["n_input"] else None,
        "output_tokens": t["n_output"],
        "total_tokens": t["n_input"] + t["n_output"],
        "subagent_tokens": t["subagent_tokens"],
        "total_tokens_inc_subagents": t["n_input"] + t["n_output"] + t["subagent_tokens"],
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

        col_x, col_y = st.columns(2)
        with col_x:
            x_axis = st.selectbox("X axis", ["time (s)", "step", "trial"], index=0)
        with col_y:
            y_axis = st.selectbox("Y axis", ["tokens", "cost (USD)"], index=0)
        only_connector = st.checkbox("Show only connector events", value=False)
        cost_mode = y_axis == "cost (USD)"
        # Style: color = connector, dash = (model, agent). Trials sharing all
        # three render identically (intentional). Each distinct (connector,
        # model, agent) combination contributes a single legend entry.
        palette = px.colors.qualitative.Plotly
        dash_cycle = ["solid", "dot", "dash", "longdash", "dashdot", "longdashdot"]
        modes_seen = sorted({t["connector"] for t in picked_trials})
        ma_seen = sorted({(t.get("model") or "?", t.get("agent") or "?") for t in picked_trials})
        color_for = {v: palette[i % len(palette)] for i, v in enumerate(modes_seen)}
        dash_for = {ma: dash_cycle[i % len(dash_cycle)] for i, ma in enumerate(ma_seen)}
        fig_tl = go.Figure()
        tool_call_rows = []
        # Per-trial cost factoring: raw = pricing-table est, scale rescales raw
        # so the final point matches Harbor's trial.cost_usd. Recorded so the
        # audit table can show est_cost_usd alongside the actual.
        cost_factor: dict[str, float] = {}
        est_cost_total: dict[str, float] = {}
        for trial_idx, t in enumerate(picked_trials, start=1):
            tl = load_trial_timeline(
                t["job"], t["trial"], mtimes.get(t["job"], 0.0), t.get("model")
            )
            est_total = tl["est_cost_total"]
            est_cost_total[f"{t['job']}/{t['trial']}"] = est_total
            actual = t.get("cost_usd") or 0.0
            scale = (actual / est_total) if (cost_mode and est_total > 0 and actual > 0) else 1.0
            cost_factor[f"{t['job']}/{t['trial']}"] = scale
            verdict = "pass" if t["tests_passed"] else ("error" if t["errored"] else "fail")
            hover_label = f"{t['trial']} · {verdict}<br>{t['job']}"
            kinds = [
                metrics_mod.classify_call_multi(
                    {"function_name": m["name"], "arguments": m["args"]},
                    t["connectors_by_app"],
                )
                for m in tl["marks"]
            ]
            connector_flags = [k == "connector" for k in kinds]
            for m, kind in zip(tl["marks"], kinds):
                tool_call_rows.append({
                    "trial": t["trial"],
                    "connector": t["connector"],
                    "t_s": round(m["t"], 2),
                    "cum_tokens": m["cum_tokens"],
                    "cum_cost_usd": round(m["cum_cost_raw"] * scale, 6),
                    "tool": m["name"],
                    "args": json.dumps(m["args"])[:300],
                    "kind": kind,
                })
            if not tl["line"]:
                continue
            mode = t["connector"]
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

            def _y(r):
                return (r["cum_cost_raw"] * scale) if cost_mode else r["cum_tokens"]

            unit = "USD" if cost_mode else "tokens"
            yfmt = "$%{y:.4f}" if cost_mode else "%{y} tokens"
            line_shown = x_axis != "trial"
            if line_shown:
                fig_tl.add_trace(go.Scatter(
                    x=[_x(r) for r in tl["line"]],
                    y=[_y(r) for r in tl["line"]],
                    mode="lines",
                    name=trace_name,
                    legendgroup=trace_group,
                    showlegend=True,
                    line=dict(color=color, dash=dash),
                    hovertemplate="%{x}<br>" + yfmt + "<extra>" + hover_label + "</extra>",
                ))
            visible_marks = [
                (m, is_ch) for m, is_ch in zip(tl["marks"], connector_flags)
                if not only_connector or is_ch
            ]
            if visible_marks:
                fig_tl.add_trace(go.Scatter(
                    x=[_x(m) for m, _ in visible_marks],
                    y=[_y(m) for m, _ in visible_marks],
                    mode="markers",
                    name=trace_name,
                    legendgroup=trace_group,
                    # If the line trace already carries the legend entry for this
                    # trial, suppress the markers' duplicate entry.
                    showlegend=not line_shown,
                    marker=dict(size=8, symbol="circle", color=color),
                    customdata=[[m["name"], json.dumps(m["args"])[:300]] for m, _ in visible_marks],
                    hovertemplate="%{x}<br>" + yfmt + "<br><b>%{customdata[0]}</b><br>%{customdata[1]}<extra>" + hover_label + "</extra>",
                ))
            del unit  # silence unused-var; format string covers display
        if not fig_tl.data:
            st.info("No trajectory.json found for the picked trials.")
        else:
            fig_tl.update_xaxes(title=x_axis)
            fig_tl.update_yaxes(title="cumulative cost (USD)" if cost_mode else "cumulative tokens")
            st.plotly_chart(fig_tl, use_container_width=True)
            if cost_mode:
                # Surface raw pricing-table estimate and rescale factor per trial so
                # mismatches with Harbor's authoritative cost_usd are visible. When
                # cost_usd is missing (opencode), factor=1.0 and we show the raw.
                audit_rows = [{
                    "trial": t["trial"],
                    "model": t.get("model") or "?",
                    "cost_usd (Harbor)": round(t.get("cost_usd") or 0.0, 6),
                    "est_cost_usd (raw)": round(est_cost_total.get(f"{t['job']}/{t['trial']}", 0.0), 6),
                    "rescale_factor": round(cost_factor.get(f"{t['job']}/{t['trial']}", 1.0), 4),
                } for t in picked_trials]
                with st.expander("Cost estimate audit (raw vs Harbor)"):
                    st.dataframe(audit_rows, hide_index=True, use_container_width=True)
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
            apps_label = t.get("apps") or "?"
            connector_label = t.get("connector") or "?"
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
                f"**Apps:** `{apps_label}`",
                f"**Connector:** `{connector_label}`",
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
                     "args": r["args"], "cum_tokens": r["cum_tokens"],
                     "cum_cost_usd": r["cum_cost_usd"]}
                    for r in tool_call_rows
                    if r["trial"] == t["trial"] and (not only_connector or r["kind"] == "connector")
                ]
                st.caption(f"{len(filtered)} call(s)")
                if filtered:
                    st.dataframe(filtered, use_container_width=True)
                else:
                    st.info("No tool calls recorded.")

            with tab_traj:
                steps_data = load_trial_steps(
                    t["job"], t["trial"], mtimes.get(t["job"], 0.0), t.get("model")
                )
                _render_trajectory_steps(
                    steps_data,
                    t["connectors_by_app"],
                    state_key=f"{t['job']}_{t['trial']}",
                    trial_cost_usd=t.get("cost_usd"),
                )
                if steps_data:
                    n_calls = sum(len(s["tool_calls"]) for s in steps_data)
                    st.caption(f"{len(steps_data)} step(s) · {n_calls} tool call(s)")

            with tab_info:
                if t["exception"]:
                    st.error(f"Exception: {t['exception']}")
                if t["failed_criteria"]:
                    st.warning(f"Failed criteria: {t['failed_criteria']}")
                if t["escape_call_values"]:
                    st.caption("Off-connector calls: " + " | ".join(t["escape_call_values"]))
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
                    _kv_row("connector calls", t["connector_calls"]),
                    _kv_row("off-connector calls", t["off_connector_calls"]),
                    _kv_row("errored calls", t["errored_calls"]),
                    _kv_row("connector output chars", f"{t['connector_output_chars']:,}"),
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
    # Per (task, agent+model, connector) avg-tokens stacked bars, faceted by row=task, col=agent+model.
    cells: dict[tuple, dict] = defaultdict(lambda: {"n_input": 0, "n_cache": 0, "n_output": 0, "count": 0})
    for t in trials:
        am = f"{t.get('agent') or '?'} / {t.get('model') or '?'}"
        key = (t["task"], am, t["connector"])
        c = cells[key]
        c["n_input"] += t["n_input"]
        c["n_cache"] += t["n_cache"]
        c["n_output"] += t["n_output"]
        c["count"] += 1
    grid_rows = []
    for (task, am, mode), c in cells.items():
        n = c["count"] or 1
        grid_rows.append({"task": task, "agent_model": am, "connector": mode,
                          "kind": "input (cached)", "tokens": c["n_cache"] / n})
        grid_rows.append({"task": task, "agent_model": am, "connector": mode,
                          "kind": "input (uncached)", "tokens": max(0, c["n_input"] - c["n_cache"]) / n})
        grid_rows.append({"task": task, "agent_model": am, "connector": mode,
                          "kind": "output", "tokens": c["n_output"] / n})
    if not grid_rows:
        st.info("No trial data in the selected jobs.")
    else:
        mode_order = sorted({r["connector"] for r in grid_rows})
        fig_grid = px.bar(
            grid_rows,
            x="connector",
            y="tokens",
            color="kind",
            facet_col="agent_model",
            facet_row="task",
            barmode="stack",
            category_orders={
                "kind": ["input (cached)", "input (uncached)", "output"],
                "connector": mode_order,
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

# (label, higher_better, fixed_range, tick_format). higher_better drives the
# colorscale direction; None means neutral (no good/bad), used for counts.
MATRIX_METRICS: dict[str, tuple[str, bool | None, tuple[float, float] | None, str]] = {
    "pass_rate": ("Pass rate", True, (0.0, 1.0), ".0%"),
    "avg_reward": ("Avg reward", True, None, ".2f"),
    "total": ("Trial count", None, None, "d"),
    "avg_cost_usd": ("Avg cost (USD)", False, None, "$.4f"),
    "avg_agent_exec_s": ("Avg agent exec (s)", False, None, ".1f"),
    "avg_connector_calls": ("Avg connector calls", None, None, ".1f"),
    "avg_off_connector_calls": ("Avg off-connector calls", False, None, ".2f"),
    "avg_errored_calls": ("Avg errored calls", False, None, ".2f"),
    "avg_total_tokens": ("Avg tokens", False, None, ",.0f"),
    "avg_total_tokens_inc_subagents": ("Avg tokens (+subagents)", False, None, ",.0f"),
    "avg_subagent_tokens": ("Avg subagent tokens", None, None, ",.0f"),
    "avg_prompt_baseline_tokens": ("Avg baseline prompt tokens", False, None, ",.0f"),
    "avg_output_tokens": ("Avg output tokens", False, None, ",.0f"),
    "avg_cache_tokens": ("Avg cached tokens", None, None, ",.0f"),
    "avg_uncached_input_tokens": ("Avg uncached tokens", False, None, ",.0f"),
    "cache_hit_rate": ("Cache hit rate", True, (0.0, 1.0), ".0%"),
}

with tab_matrix:
    st.caption("Pivot trials into a matrix. Pick row/column dimensions and the cell metric.")
    matrix_dim_options = [k for k in GROUP_KEYS if k != "trial"]
    c1, c2, c3 = st.columns(3)
    with c1:
        row_dims = st.multiselect(
            "Rows", matrix_dim_options, default=["task"], key="mx_rows",
        )
    with c2:
        col_dims = st.multiselect(
            "Columns", matrix_dim_options, default=["agent", "model", "connector"], key="mx_cols",
        )
    with c3:
        metric = st.selectbox(
            "Value", list(MATRIX_METRICS.keys()),
            format_func=lambda k: MATRIX_METRICS[k][0], key="mx_metric",
        )
    label, higher_better, fixed_range, tick_fmt = MATRIX_METRICS[metric]

    matrix_trials = trials

    if not row_dims or not col_dims:
        st.info("Pick at least one row and one column dimension.")
    elif not matrix_trials:
        st.warning("No trials match the current filters.")
    else:
        cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for t in matrix_trials:
            rk = " | ".join(str(t.get(d) or "?") for d in row_dims)
            ck = " | ".join(str(t.get(d) or "?") for d in col_dims)
            cells[(rk, ck)].append(t)
        row_labels = sorted({rk for rk, _ in cells})
        col_labels = sorted({ck for _, ck in cells})
        # by=[] makes aggregate() collapse the cell's trials into one group;
        # reusing it keeps metric definitions in lockstep with the Grouped tab.
        z: list[list[float | None]] = [[None] * len(col_labels) for _ in row_labels]
        counts: list[list[int]] = [[0] * len(col_labels) for _ in row_labels]
        for (rk, ck), ts in cells.items():
            r_idx = row_labels.index(rk)
            c_idx = col_labels.index(ck)
            agg = aggregate(ts, [])[0]
            z[r_idx][c_idx] = agg.get(metric)
            counts[r_idx][c_idx] = agg["total"]

        if higher_better is True:
            colorscale = "RdYlGn"
        elif higher_better is False:
            colorscale = "RdYlGn_r"
        else:
            colorscale = "Blues"

        text = [
            [
                ("" if z[i][j] is None else format(z[i][j], tick_fmt.replace("$", "")))
                for j in range(len(col_labels))
            ]
            for i in range(len(row_labels))
        ]
        hover = [
            [
                (
                    f"{' | '.join(row_dims)}: {row_labels[i]}<br>"
                    f"{' | '.join(col_dims)}: {col_labels[j]}<br>"
                    f"{label}: {'-' if z[i][j] is None else format(z[i][j], tick_fmt.lstrip('$,'))}<br>"
                    f"trials: {counts[i][j]}"
                )
                for j in range(len(col_labels))
            ]
            for i in range(len(row_labels))
        ]
        fig_mx = go.Figure(
            go.Heatmap(
                z=z, x=col_labels, y=row_labels,
                colorscale=colorscale,
                zmin=fixed_range[0] if fixed_range else None,
                zmax=fixed_range[1] if fixed_range else None,
                text=text, texttemplate="%{text}",
                hoverinfo="text", hovertext=hover,
                colorbar=dict(title=label, tickformat=tick_fmt),
            )
        )
        fig_mx.update_xaxes(title=" | ".join(col_dims), side="top")
        fig_mx.update_yaxes(title=" | ".join(row_dims), autorange="reversed")
        fig_mx.update_layout(
            height=max(240, 60 + 36 * len(row_labels)),
            margin=dict(l=80, r=20, t=80, b=40),
        )
        st.plotly_chart(fig_mx, use_container_width=True)
