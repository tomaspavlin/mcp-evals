# mcp-evals

What this project is: see `AGENTS.md`.

## Prerequisites

- **Python 3.13+** (Harbor requires 3.12+; we use 3.13.7)
- **Docker** — local execution. OrbStack works (drop-in for Docker Desktop). Only needed for the `--env docker` path; cloud sandboxes skip this.
- **OpenRouter account** — single key for all LLM providers. https://openrouter.ai/keys
- **Daytona account** (recommended cloud sandbox) — https://app.daytona.io. We prefer Daytona over E2B because **E2B's free tier caps sandbox lifetime at 1h** and Harbor hardcodes `timeout=86_400` (`harbor/environments/e2b.py:198`), so every E2B run fails on free tier. Daytona has no such trap.

## Install

```bash
pipx install harbor && pipx inject harbor daytona
```

Verify: `harbor --version` and `harbor datasets list`.

## Configure secrets

```bash
cp .env.example .env
# edit .env — at minimum set OPENROUTER_API_KEY (and DAYTONA_API_KEY if using cloud)
```

Load env vars before running Harbor:

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

```bash
harbor run -c configs/swebench-haiku-smoketest.yaml -m anthropic/claude-sonnet-4.6 --job-name swebench-sonnet-smoketest
```

## Running a config

```bash
set -a; source .env; set +a
harbor run -c configs/apify-all-haiku-smoketest.yaml
```

## Viewing results

```bash
harbor view jobs/
```

or `harbor view jobs/<job-name>/`
