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
apps/dashboard/.venv/bin/streamlit run apps/dashboard/app.py
```

Opens at http://localhost:8501. Pick jobs in the sidebar.

## Layout

- `app.py` - single-page Streamlit entry point.
- `requirements.txt` - `streamlit`, `plotly`. Harbor is installed separately (editable from `../harbor`).
