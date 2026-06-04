from pathlib import Path

import plotly.express as px
import streamlit as st

from harbor.viewer.scanner import JobScanner

JOBS_DIR = Path(__file__).resolve().parents[2] / "jobs"

st.set_page_config(page_title="mcp-evals dashboard", layout="wide")
st.title("mcp-evals dashboard")

scanner = JobScanner(JOBS_DIR)
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

rows = []
for name in selected:
    result = scanner.get_job_result(name)
    if result is None:
        continue
    s = result.stats
    completed = s.n_completed_trials
    errored = s.n_errored_trials
    total = result.n_total_trials or (completed + errored) or 1
    rows.append({
        "job": name,
        "total": result.n_total_trials,
        "completed": completed,
        "errored": errored,
        "pass_rate": (completed - errored) / total if total else 0.0,
        "cost_usd": s.cost_usd,
        "input_tokens": s.n_input_tokens,
        "output_tokens": s.n_output_tokens,
    })

if not rows:
    st.warning("Selected jobs have no result.json yet.")
    st.stop()

st.subheader("Summary")
st.dataframe(rows, use_container_width=True)

st.subheader("Pass rate")
fig = px.bar(rows, x="job", y="pass_rate", hover_data=["completed", "errored", "total"])
fig.update_yaxes(range=[0, 1])
st.plotly_chart(fig, use_container_width=True)
