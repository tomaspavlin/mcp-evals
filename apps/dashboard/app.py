from collections import defaultdict
from pathlib import Path

import plotly.express as px
import streamlit as st

from harbor.viewer.scanner import JobScanner

JOBS_DIR = Path(__file__).resolve().parents[2] / "jobs"
KNOWN_VARIANTS = {"mcp", "cli", "skill", "mcpc"}
GROUP_KEYS = ["job", "variant", "task", "agent", "model"]

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
        # Match the job-level `(n_completed - n_errored)/total` semantics from
        # harbor/models/job/result.py: every recorded trial counts as completed.
        passed = not errored
        model_name = None
        if tr.config and tr.config.agent:
            model_name = tr.config.agent.model_name
        out.append({
            "job": job_name,
            "variant": parse_variant(job_name),
            "task": tr.task_name,
            "agent": tr.agent_info.name if tr.agent_info else None,
            "model": model_name,
            "passed": passed,
            "errored": errored,
            "n_input": n_in or 0,
            "n_cache": n_cache or 0,
            "n_output": n_out or 0,
            "cost_usd": cost or 0.0,
        })
    return out


def aggregate(trials: list[dict], by: list[str]) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {
        "completed": 0, "errored": 0, "total": 0,
        "cost_usd": 0.0, "n_input": 0, "n_cache": 0, "n_output": 0,
    })
    for t in trials:
        key = " | ".join(str(t.get(b) or "?") for b in by)
        g = groups[key]
        g["total"] += 1
        if t["errored"]:
            g["errored"] += 1
        elif t["passed"]:
            g["completed"] += 1
        g["cost_usd"] += t["cost_usd"]
        g["n_input"] += t["n_input"]
        g["n_cache"] += t["n_cache"]
        g["n_output"] += t["n_output"]
    rows = []
    for key, g in groups.items():
        total = g["total"] or 1
        rows.append({
            "group": key,
            "total": g["total"],
            "completed": g["completed"],
            "errored": g["errored"],
            "pass_rate": (g["completed"] - g["errored"]) / total,
            "cost_usd": g["cost_usd"],
            "input_tokens": g["n_input"],
            "cache_tokens": g["n_cache"],
            "output_tokens": g["n_output"],
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

group_by = st.sidebar.multiselect("Group by", GROUP_KEYS, default=["job"])
if not group_by:
    st.info("Pick at least one grouping dimension in the sidebar.")
    st.stop()

mtimes = {p.name: p.stat().st_mtime for p in job_dirs}
trials: list[dict] = []
for name in selected:
    trials.extend(load_trial_rows(name, mtimes.get(name, 0.0)))

if not trials:
    st.warning("Selected jobs have no trial results yet.")
    st.stop()

rows = aggregate(trials, group_by)

st.subheader(f"Summary (grouped by {' | '.join(group_by)})")
st.dataframe(rows, use_container_width=True)

st.subheader("Pass rate")
fig = px.bar(rows, x="group", y="pass_rate", hover_data=["completed", "errored", "total"])
fig.update_xaxes(title=" | ".join(group_by))
fig.update_yaxes(range=[0, 1])
st.plotly_chart(fig, use_container_width=True)

st.subheader("Cost (USD)")
fig_cost = px.bar(rows, x="group", y="cost_usd", hover_data=["input_tokens", "cache_tokens", "output_tokens"])
fig_cost.update_xaxes(title=" | ".join(group_by))
st.plotly_chart(fig_cost, use_container_width=True)

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
