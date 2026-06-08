# mcp-evals

What this project is: see `AGENTS.md`.

## Prerequisites

- **Python 3.13+** (Harbor requires 3.12+; we use 3.13.7)
- **Docker** — local execution. OrbStack works (drop-in for Docker Desktop). Only needed for the `--env docker` path; cloud sandboxes skip this.
- **OpenRouter account** — single key for all LLM providers. https://openrouter.ai/keys
- **Daytona account** (recommended cloud sandbox) — https://app.daytona.io. We prefer Daytona over E2B because **E2B's free tier caps sandbox lifetime at 1h** and Harbor hardcodes `timeout=86_400` (`harbor/environments/e2b.py:198`), so every E2B run fails on free tier. Daytona has no such trap.

## Install

```bash
uv sync                                  # creates .venv, installs harbor + mcp-evals
pipx inject harbor daytona               # optional: for cloud sandbox path
```

Verify: `uv run mcp-evals run --help` and `uv run harbor --version`.

`harbor` is also available as a standalone tool (`pipx install harbor`) if you want to run legacy configs without going through `uv run`.

## Configure secrets

```bash
cp .env.example .env
# edit .env — at minimum set OPENROUTER_API_KEY (and DAYTONA_API_KEY if using cloud)
```

`mcp-evals run` auto-loads `.env` from cwd. For raw `harbor run` you still need:

```bash
set -a; source .env; set +a
# or use direnv: echo 'dotenv' > .envrc && direnv allow
```

## Smoke tests

Zero-cost (no LLM, just verifies Harbor + sandbox loop):
```bash
harbor run -t hello-world/hello-world -a oracle --env daytona
```

Real LLM via OpenRouter (cents):
```bash
harbor run -t hello-world/hello-world -a claude-code -m anthropic/claude-haiku-4.5 --env daytona
```

## Running

From a config:
```bash
uv run mcp-evals run -c configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml -y
```

Ad-hoc via flags (no config file needed):
```bash
uv run mcp-evals run --integration apify-mcp -a oracle -t tasks/apify-fetch-actor-id -y
uv run mcp-evals run --integration apify-mcp -a oracle \
  --dataset-path tasks --task-name 'apify-*' -y
```

See `configs/` for the schema and `uv run mcp-evals run --help` for all flags.

## Viewing results

```bash
harbor view jobs
```

Project-specific plots (MCP vs CLI vs skill comparisons, etc.) live in a custom app:

```bash
apps/dashboard/.venv/bin/streamlit run apps/dashboard/app.py
```

See `apps/dashboard/README.md` for first-time setup.

## Viewing tasks

```bash
harbor view tasks
```
