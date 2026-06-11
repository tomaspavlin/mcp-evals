# dashboard

Custom Streamlit dashboard over `jobs/`. Complements `harbor view jobs` with project-specific plots (MCP vs CLI vs skill comparisons, cost/token efficiency, pass-rate breakdowns).

Reads job data via Harbor's `JobScanner` (`harbor.viewer.scanner`), so `config.json` / `result.json` parsing stays in sync with Harbor's Pydantic models.

## Setup

```bash
python3 -m venv apps/dashboard/.venv
apps/dashboard/.venv/bin/pip install -r apps/dashboard/requirements.txt
apps/dashboard/.venv/bin/pip install -e ../harbor   # provides harbor.viewer.scanner
```

## Run

```bash
uv run mcp-evals dashboard                 # ./jobs
uv run mcp-evals dashboard evals/jobs      # any other jobs dir
```

Flags: `-p/--port` (default 8501), `--host` (default localhost), `--no-browser`.
The command prefers this directory's `.venv/bin/streamlit`, falls back to
`streamlit` on PATH, and passes the jobs dir via `MCP_EVALS_JOBS_DIR`.

## Layout

- `app.py` - single-page Streamlit entry point. Loads `src/mcp_evals/metrics.py` by file
  path (stdlib-only), so the mcp_evals package does not need to be installed in this venv.
- `requirements.txt` - `streamlit`, `plotly`. Harbor is installed separately (editable from `../harbor`).
