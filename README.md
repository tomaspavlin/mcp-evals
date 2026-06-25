# mcp-evals

Develop, test, and evaluate the tools you give to AI agents: MCP servers,
skills, CLI tools. Real agents (claude-code, codex, opencode) run verifiable
tasks against your tooling, so you can compare tool-access strategies (MCP vs
CLI vs skill) across harnesses and models and measure success rate, token/cost
efficiency, and tool-call behavior. Built on
[Harbor](https://www.harborframework.com/docs).

How it works:

1. Define an **app** (a third-party service: apify, github, ...) under
   `apps/<name>/<connector>/` for each access **connector** you want to
   compare: `mcp`, `cli`, `mcpc`, `cli+skill`. Each cell holds the MCP server
   config, the CLI setup, or the skill the agent gets.
2. Define tasks in `tasks/`: an instruction the agent should accomplish, plus
   a verifier. Each task declares which apps it needs via
   `[mcp_evals].apps = [...]` in its `task.toml` - one task can use
   several apps (e.g. apify + github together).
3. `mcp-evals run` launches the agents in sandboxes on every task with the
   chosen connector(s) wired up, and runs the verifiers.
4. Results, including full execution traces, are stored structured under
   `jobs/`. Inspect them in the results browser or dashboard, or point a coding
   agent (e.g. Claude Code) at them to diagnose failures and iterate on your
   skills and apps.

## Concepts

Harbor primitives (Task, Trial, Job, Agent, Environment, Dataset) are documented
at https://www.harborframework.com/docs/core-concepts. `mcp-evals` adds two
project-specific axes on top:

- **app** - third-party service the agent talks to (`apify`, `github`, `linear`, `notion`, ...).
- **connector** - how the agent reaches it: `mcp`, `cli`, `mcpc`, or `cli+skill`. One connector per run by default; `app_connectors:` for hybrid.
- **cell** - one (app, connector) pair on disk: `apps/<app>/<connector>/{cell.yaml, instruction.md, [setup.sh], [teardown.sh], [skills/]}`.

Deep reference (cell file layout, `cell.yaml` fields, MCP-proxy wrapper template,
verifier env contract, step-by-step for wiring a new app):
[`docs/mcp-task-pattern.md`](docs/mcp-task-pattern.md).

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

- `apps/<app>/<connector>/` - `cell.yaml` (MCP servers, env, setup_env)
  plus optional `instruction.md`, `setup.sh`, `teardown.sh`, `skills/`. Examples
  in this repo's `apps/`.
- `tasks/<name>/` - Harbor task dirs (`task.toml`, instruction, verifier).
  `task.toml` declares which apps the task needs via `[mcp_evals].apps`.
- `images/base/Dockerfile` - one shared sandbox image with every app tool
  installed; copied unchanged into each task's `environment/` at run time.

```
mcp-evals run [-c CONFIG] [--connector CONNECTOR] [--app NAME]...
              [--apps-dir PATH] [-a AGENT] [-m MODEL]
              [-t TASK]... [-p DATASET_PATH]
              [--task-name GLOB]... [--exclude-task-name GLOB]...
              [--job-name NAME] [-o JOBS_DIR] [-k N_ATTEMPTS] [-n N_CONCURRENT]
              [--env BACKEND] [--env-file PATH] [-y]
```

Every flag overrides the corresponding config field; `mcp-evals run --help` for
details. Defaults: E2B sandbox (`--env docker` / `--env daytona` to switch),
`./apps`, `./jobs`.

### Examples

One task, one agent (apps auto-resolved from `task.toml`):

```bash
mcp-evals run --connector mcp -t tasks/my-task \
  -a claude-code -m anthropic/claude-haiku-4.5 -y
```

A multi-app task (one task, two apps wired up at once):

```bash
mcp-evals run --connector mcp -t tasks/cross-actor-meta-and-repo-meta -a oracle -y
```

A whole task dataset with name filtering, oracle agent (replays the reference
solution, no LLM):

```bash
mcp-evals run --connector mcp -a oracle \
  --dataset-path tasks --task-name 'apify-*' -y
```

From a config (see `configs/` in this repo for the schema):

```bash
mcp-evals run -c configs/my-eval.yaml -y
```

Eval definitions somewhere else than the cwd (e.g. inside an app repo):

```bash
mcp-evals run --apps-dir evals/apps -t evals/tasks/my-task \
  -o evals/jobs --connector mcp -a claude-code -m ... -y
```

### Path notes

- `--apps-dir` is also a config field (`apps_dir`); `-o/--jobs-dir`
  matches `harbor run`.
- Paths in a config file resolve relative to the cwd, not the config location.
- Explicit `skills:` entries in `cell.yaml` resolve relative to that yaml's
  directory and support globs (`skills: ["../../src/lib/skills/*"]`). Each
  match must be a directory with a `SKILL.md`; a pattern matching nothing is
  an error. The sibling `skills/` subdir is still auto-discovered and
  de-duplicated against explicit entries.
- Every task's `environment/` is materialized by copying `images/base/` into
  it (replacing whatever is there). Harbor requires `environment/` inside the
  task dir, so this cannot be redirected; gitignore `tasks/*/environment/`,
  as this repo does.

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
`dashboard/README.md` for first-time setup (dedicated streamlit venv).

## Known limitations

- Codex trajectories carry no per-step token metrics (harbor converter gap), so the
  `prompt_baseline_tokens` metric and the dashboard's token timeline are unavailable for
  codex trials; per-trial totals are unaffected. See `docs/harbor-constraints.md` and
  `docs/todo.md`.
- Opencode truncates large tool outputs in the trajectory (the observation records a
  "Full output saved to: ..." stub instead of the full content), so `connector_output_chars`
  undercounts for verbose calls; cli/mcpc variants benefit most from this. Token totals
  are unaffected (reported by the API, not derived from content). See `docs/todo.md`.
- Connector sweeps over the same task now share one Dockerfile (`images/base/`), so the
  old "don't run same-task configs in parallel" restriction is lifted. Two runs against
  the same task with different connectors can run concurrently; the materialized
  `environment/` is identical so the sandbox template cache is reused either way.
- First-time e2b template builds for the same task can race and cross-cancel
  (`BuildException` / `SandboxException 404`). Pre-warm with
  `configs/all-opencode-deepseek-mcp-prewarm.yaml` before parallel sweeps.
- E2B accepts heavy concurrency: a 17-trial sweep with `-n 17` ran with zero
  sandbox / quota / 429 errors. Set `-n` to whatever your dataset size / API rate
  limits allow; the sandbox layer is not the bottleneck.

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
uv run mcp-evals run --connector mcp -t tasks/apify-fetch-actor-id -a oracle -y
```

Real LLM via OpenRouter (cents):

```bash
uv run mcp-evals run --connector mcp -t tasks/apify-fetch-actor-id -a claude-code -m anthropic/claude-haiku-4.5 -y
```

`harbor` is also usable standalone (`pipx install harbor`; add
`pipx inject harbor daytona` for the `--env daytona` path). For raw
`harbor run`, `.env` is not auto-loaded:

```bash
set -a; source .env; set +a
# or use direnv: echo 'dotenv' > .envrc && direnv allow
```
