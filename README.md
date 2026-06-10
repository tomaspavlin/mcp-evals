# mcp-evals

What this project is: see `AGENTS.md`.

## Prerequisites

- **Python 3.13+** (Harbor requires 3.12+; we use 3.13.7)
- **OpenRouter account** — single key for all LLM providers. https://openrouter.ai/keys
- **E2B account** (default sandbox) — https://e2b.dev. Set `E2B_API_KEY` in `.env`.
- **Daytona account** (alternative cloud sandbox, `--env daytona`) — https://app.daytona.io.
- **Docker** (alternative local sandbox, `--env docker`) — OrbStack works.

## Install

```bash
uv sync                                  # creates .venv, installs harbor[e2b] + mcp-evals
pipx inject harbor daytona               # optional: for the --env daytona path
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
uv run mcp-evals run --integration apify-mcp -t tasks/apify-fetch-actor-id -a oracle -y
```

Real LLM via OpenRouter (cents):
```bash
uv run mcp-evals run --integration apify-mcp -t tasks/apify-fetch-actor-id -a claude-code -m anthropic/claude-haiku-4.5 -y
```

Defaults to E2B; pass `--env docker` or `--env daytona` to switch backends.

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
