# mcp-evals

Develop, test, and evaluate the tools you give to AI agents: MCP servers,
skills, CLI tools. Real agents (claude-code, codex, opencode) run verifiable
tasks against your tooling, so you can compare tool-access strategies (MCP vs
CLI vs skill) across harnesses and models and measure success rate, token/cost
efficiency, and tool-call behavior. Built on
[Harbor](https://www.harborframework.com/docs).

How it works:

1. Define each tool-access variant as an integration in `integrations/`: the
   MCP server config, skills, or CLI setup the agent gets. Define as many
   variants as you want to compare or iterate on.
2. Define tasks in `tasks/`: an instruction the agent should accomplish using
   that tooling, plus a verifier that automatically decides whether it
   succeeded.
3. `mcp-evals run` launches the agents in sandboxes on every task and runs the
   verifiers.
4. Results, including full execution traces, are stored structured under
   `jobs/`. Inspect them in the results browser or dashboard, or point a coding
   agent (e.g. Claude Code) at them to diagnose failures and iterate on your
   skills and integrations.

## Installation

```bash
uv tool install git+https://github.com/tomaspavlin/mcp-evals
```

From a local fork/checkout instead (changes in the checkout apply immediately,
no reinstall):

```bash
uv tool install --editable /path/to/mcp-evals
```

To use it as a library (`from mcp_evals import ...`) add it as a project
dependency instead: `uv add git+https://github.com/tomaspavlin/mcp-evals`, then
invoke the CLI via `uv run mcp-evals`.

## Prerequisites

- **OpenRouter account** — single key for all LLM providers. https://openrouter.ai/keys
- **E2B account** (default sandbox) — https://e2b.dev
- **Daytona account** (alternative cloud sandbox, `--env daytona`) — https://app.daytona.io
- **Docker** (alternative local sandbox, `--env docker`) — OrbStack works.

Put keys in a `.env` in the directory you run from — `mcp-evals run` auto-loads
it (`--env-file` overrides). At minimum `OPENROUTER_API_KEY` plus the sandbox
key (`E2B_API_KEY` by default).

## Usage

The CLI reads eval definitions relative to the directory you run it from:

- `integrations/<name>/` — `integration.yaml` (MCP servers, skills, env) plus
  optional `instruction.md`, `setup.sh`, `environment/`, `skills/`. Examples in
  this repo's `integrations/`.
- `tasks/<name>/` — Harbor task dirs (`task.toml`, instruction, verifier).

```
mcp-evals run [-c CONFIG] [--integration NAME] [--integrations-dir PATH]
              [-a AGENT] [-m MODEL] [-t TASK]... [-p DATASET_PATH]
              [--task-name GLOB]... [--exclude-task-name GLOB]...
              [--job-name NAME] [-o JOBS_DIR] [-k N_ATTEMPTS] [-n N_CONCURRENT]
              [--env BACKEND] [--env-file PATH] [-y]
```

Every flag overrides the corresponding config field; `mcp-evals run --help` for
details. Defaults: E2B sandbox (`--env docker` / `--env daytona` to switch),
`./integrations`, `./jobs`.

### Examples

One task, one agent:

```bash
mcp-evals run --integration my-integration -t tasks/my-task \
  -a claude-code -m anthropic/claude-haiku-4.5 -y
```

A whole task dataset with name filtering, oracle agent (replays the reference
solution, no LLM):

```bash
mcp-evals run --integration my-integration -a oracle \
  --dataset-path tasks --task-name 'my-*' -y
```

From a config (see `configs/` in this repo for the schema):

```bash
mcp-evals run -c configs/my-eval.yaml -y
```

Eval definitions somewhere else than the cwd (e.g. inside an app repo):

```bash
mcp-evals run --integrations-dir evals/integrations -t evals/tasks/my-task \
  -o evals/jobs --integration my-integration -a claude-code -m ... -y
```

### Path notes

- `--integrations-dir` is also a config field (`integrations_dir`) and is
  accepted by `mcp-evals materialize` too; `-o/--jobs-dir` matches `harbor run`.
- Paths in a config file resolve relative to the cwd, not the config location.
- Explicit `skills:` entries in `integration.yaml` resolve relative to that
  yaml's directory and support globs (`skills: ["../../src/lib/skills/*"]`).
  Each match must be a directory with a `SKILL.md`; a pattern matching nothing
  is an error. The sibling `skills/` subdir is still auto-discovered and
  de-duplicated against explicit entries.
- Integrations with an `environment/` dir are materialized by copying it into
  each task dir as `tasks/<name>/environment/` (replacing whatever is there).
  Harbor requires `environment/` inside the task dir, so this cannot be
  redirected; gitignore `tasks/*/environment/`, as this repo does.

## Viewing results

```bash
harbor view jobs    # trial browser
harbor view tasks   # task browser
```

Project-specific plots (MCP vs CLI vs skill comparisons, etc.) live in a custom app:

```bash
mcp-evals dashboard                # ./jobs
mcp-evals dashboard evals/jobs     # any other jobs dir, e.g. from an app repo
```

Flags: `-p/--port` (default 8501), `--host`, `--no-browser`. See
`apps/dashboard/README.md` for first-time setup (dedicated streamlit venv).

## Known limitations

- Codex trajectories carry no per-step token metrics (harbor converter gap), so the
  `prompt_baseline_tokens` metric and the dashboard's token timeline are unavailable for
  codex trials; per-trial totals are unaffected. See `docs/todo.md`.
- Opencode truncates large tool outputs in the trajectory (the observation records a
  "Full output saved to: ..." stub instead of the full content), so `channel_output_chars`
  undercounts for verbose calls; cli/mcpc variants benefit most from this. Token totals
  are unaffected (reported by the API, not derived from content). See `docs/todo.md`.

## Credits

The GitHub task suite (`tasks/github-*`) is ported from the `bench-github`
benchmark in [kunchenguid/axi](https://github.com/kunchenguid/axi) - task
prompts and grading hints are reused, re-expressed as Harbor trajectory-judge
tasks. Thanks to that project.

## Development

Project goals, architecture, and conventions: see `AGENTS.md` and `docs/`.
Requires Python 3.13+.

```bash
uv sync                                  # creates .venv, installs harbor[e2b] + mcp-evals
cp .env.example .env                     # then set OPENROUTER_API_KEY, E2B_API_KEY, ...
uv run pytest                            # unit tests
```

Smoke tests against the bundled evals — zero-cost (no LLM, just verifies the
Harbor + sandbox loop):

```bash
uv run mcp-evals run --integration apify-mcp -t tasks/apify-fetch-actor-id -a oracle -y
```

Real LLM via OpenRouter (cents):

```bash
uv run mcp-evals run --integration apify-mcp -t tasks/apify-fetch-actor-id -a claude-code -m anthropic/claude-haiku-4.5 -y
```

`harbor` is also usable standalone (`pipx install harbor`; add
`pipx inject harbor daytona` for the `--env daytona` path). For raw
`harbor run`, `.env` is not auto-loaded:

```bash
set -a; source .env; set +a
# or use direnv: echo 'dotenv' > .envrc && direnv allow
```
