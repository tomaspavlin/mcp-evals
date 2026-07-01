# connector-evals

Evaluate the tools you give to AI agents: MCP servers, skills, CLI tools. Real
agents (claude-code, codex, opencode) run verifiable tasks against your
tooling, so you can compare tool-access strategies (MCP vs CLI vs skill) across
harnesses and models and measure success rate, token/cost efficiency, and
tool-call behavior. Built on [Harbor](https://www.harborframework.com/docs).

Also usable as a dev loop when building new MCP servers or skills: every trial
stores the full execution trace, so you can diagnose failures and iterate on
your tooling directly (point a coding agent at the traces under `jobs/`).

**Features:**

- 📊 Side-by-side comparison of tool access: **MCP / CLI / skill / [mcpc](https://github.com/apify/mcpc)**
- 🤖 Multi-harness: **claude-code, codex, opencode**
- 🧠 Multi-model via OpenRouter or direct-to-provider
- 🔗 Cross-app tasks: one instruction can touch multiple apps at once (apify + github + ...)
- 📜 Full trajectory traces, verifier scores, and per-trial token/cost breakdowns
- 📈 Project dashboard with connector-comparison plots
- ☁️ Cloud sandboxes (E2B, Daytona, ...) or local Docker
- 🧩 Extensible: add apps or tasks by dropping a directory, no code changes
- 🐚 Built on [Harbor](https://www.harborframework.com/docs)

## Concepts

Harbor primitives (full reference:
https://www.harborframework.com/docs/core-concepts):

- **task** - one test case: an instruction plus a verifier that scores the result.
- **dataset** - a collection of tasks.
- **agent** - the CLI harness that completes the task (claude-code, codex, opencode, ...).
- **environment** - the container the agent runs in (docker, e2b, daytona, ...).
- **trial** - one (task, agent, model) execution; produces a reward.
- **job** - a collection of trials, run in parallel.

`connector-evals` adds three project-specific pieces on top:

- **app** - third-party service the agent talks to (`apify`, `github`, `linear`, `notion`, ...).
- **connector** - how the agent reaches it: `mcp`, `cli`, `mcpc`, or `cli+skill`. One connector per run by default; `app_connectors:` for hybrid.
- **cell** - one (app, connector) pair on disk: `apps/<app>/<connector>/{cell.yaml, instruction.md, [setup.sh], [teardown.sh], [skills/]}`.

Workflow:

1. Create a **cell** for each `(app, connector)` pair you want to compare under
   `apps/<app>/<connector>/`.
2. Define tasks in `tasks/`: an instruction the agent should accomplish plus a
   verifier. Each task declares which apps it needs via
   `[connector_evals].apps = [...]` in its `task.toml`; one task can use
   several apps at once (e.g. apify + github).
3. `connector-evals run` launches the agents in sandboxes on every task with
   the chosen connector(s) wired up, and runs the verifiers.
4. Results and full execution traces land under `jobs/`. Inspect with the
   results browser, the dashboard, or by pointing a coding agent at them.

Deep reference (cell file layout, `cell.yaml` fields, MCP-proxy wrapper template,
verifier env contract, step-by-step for wiring a new app):
[`docs/mcp-task-pattern.md`](docs/mcp-task-pattern.md).

## Installation

```bash
uv tool install git+https://github.com/apify-projects/connector-evals
```

From a local fork/checkout instead (changes in the checkout apply immediately,
no reinstall):

```bash
uv tool install --editable /path/to/connector-evals
```

To use it as a library (`from connector_evals import ...`) add it as a project
dependency instead: `uv add git+https://github.com/apify-projects/connector-evals`, then
invoke the CLI via `uv run connector-evals`.

## Prerequisites

- **OpenRouter account** - single key for all LLM providers. https://openrouter.ai/keys
- **E2B account** (default sandbox) - https://e2b.dev
- **Daytona account** (alternative cloud sandbox, `--env daytona`) - https://app.daytona.io
- **Docker** (alternative local sandbox, `--env docker`) - OrbStack works.

Put keys in a `.env` in the directory you run from; `connector-evals run` auto-loads
it (`--env-file` overrides). At minimum `OPENROUTER_API_KEY` plus the sandbox
key (`E2B_API_KEY` by default).

## Usage

The CLI reads eval definitions relative to the directory you run it from:

- `apps/<app>/<connector>/` - `cell.yaml` (MCP servers, env, setup_env)
  plus optional `instruction.md`, `setup.sh`, `teardown.sh`, `skills/`. Examples
  in this repo's `apps/`.
- `tasks/<name>/` - Harbor task dirs (`task.toml`, instruction, verifier).
  `task.toml` declares which apps the task needs via `[connector_evals].apps`.
- `images/base/Dockerfile` - one shared sandbox image with every app tool
  installed; copied unchanged into each task's `environment/` at run time.

```
connector-evals run [-c CONFIG] [--connector CONNECTOR] [--app NAME]...
              [--apps-dir PATH] [-a AGENT] [-m MODEL]
              [-t TASK]... [-p DATASET_PATH]
              [--task-name GLOB]... [--exclude-task-name GLOB]...
              [--job-name NAME] [-o JOBS_DIR] [-k N_ATTEMPTS] [-n N_CONCURRENT]
              [--env BACKEND] [--env-file PATH] [-y]
```

Every flag overrides the corresponding config field; `connector-evals run --help` for
details. Defaults: E2B sandbox (`--env docker` / `--env daytona` to switch),
`./apps`, `./jobs`.

### Examples

One task, one agent (apps auto-resolved from `task.toml`):

```bash
connector-evals run --connector mcp -t tasks/my-task \
  -a claude-code -m anthropic/claude-haiku-4.5 -y
```

A multi-app task (one task, two apps wired up at once):

```bash
connector-evals run --connector mcp -t tasks/cross-actor-meta-and-repo-meta -a oracle -y
```

A whole task dataset with name filtering, oracle agent (replays the reference
solution, no LLM):

```bash
connector-evals run --connector mcp -a oracle \
  --dataset-path tasks --task-name 'apify-*' -y
```

From a config (see `configs/` in this repo for the schema):

```bash
connector-evals run -c configs/my-eval.yaml -y
```

Eval definitions somewhere else than the cwd (e.g. inside an app repo):

```bash
connector-evals run --apps-dir evals/apps -t evals/tasks/my-task \
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
- Every task's `environment/` is materialized at run time by copying
  `images/base/` into it (replacing whatever is there). Harbor requires
  `environment/` inside the task dir, so this cannot be redirected; gitignore
  `tasks/*/environment/`, as this repo does.

## Viewing results

Project dashboard (MCP vs CLI vs skill comparisons and other project-specific
plots):

```bash
connector-evals dashboard [JOBS_DIR]     # defaults to ./jobs
```

`connector-evals dashboard --help` for flags. See `dashboard/README.md` for
first-time setup (dedicated streamlit venv).

Harbor's generic browsers are also available for per-trial inspection:

```bash
harbor view jobs    # trial browser
harbor view tasks   # task browser
```

## Known limitations

- Codex trajectories carry no per-step token metrics (harbor converter gap), so the
  `prompt_baseline_tokens` metric and the dashboard's token timeline are unavailable for
  codex trials; per-trial totals are unaffected. See `docs/harbor-constraints.md` and
  `docs/todo.md`.
- Opencode truncates large tool outputs in the trajectory (the observation records a
  "Full output saved to: ..." stub instead of the full content), so `connector_output_chars`
  undercounts for verbose calls; cli/mcpc variants benefit most from this. Token totals
  are unaffected (reported by the API, not derived from content). See `docs/todo.md`.
- First-time e2b template builds for the same task can race and cross-cancel
  (`BuildException` / `SandboxException 404`). Pre-warm with one of the
  `configs/*-prewarm.yaml` configs before parallel sweeps. E2B itself accepts
  heavy concurrency once templates are warm: a 17-trial sweep with `-n 17` ran
  with zero sandbox / quota / 429 errors, so set `-n` to whatever your dataset
  size and upstream API rate limits allow.
- If a run aborts with `FileExistsError` on `jobs/<job-name>/`, the previous
  run left the dir behind: `rm -rf jobs/<job-name>` and rerun.
- Apify MCP sweeps need `-n ≤ 3`. Higher concurrency times out the stdio probe
  during MCP server startup. Applies to `--connector mcp` runs touching the
  `apify` app; other connectors and other apps are unaffected.
- OpenRouter models (`-m openrouter/...`) must pin a provider preset or prompt
  caching drops to ~0 across turns, since OpenRouter re-routes providers per
  request. Use `@preset/<provider>-only`, e.g.
  `openrouter/anthropic/claude-haiku-4.5@preset/anthropic-provider-only`. See
  AGENTS.md § Models.

## Credits

GitHub tasks (`tasks/github-*`) are ported from `bench-github` in
[kunchenguid/axi](https://github.com/kunchenguid/axi).

## Development

Project goals, architecture, and conventions: see `AGENTS.md` and `docs/`.
Requires Python 3.13+.

```bash
uv sync                                  # creates .venv, installs harbor[e2b] + connector-evals
cp .env.example .env                     # then set OPENROUTER_API_KEY, E2B_API_KEY, ...
uv run pytest                            # unit tests
```

Smoke tests against the bundled evals, zero-cost (no LLM, just verifies the
Harbor + sandbox loop):

```bash
uv run connector-evals run --connector mcp -t tasks/apify-fetch-actor-id -a oracle -y
```

Real LLM via OpenRouter (cents):

```bash
uv run connector-evals run --connector mcp -t tasks/apify-fetch-actor-id -a claude-code -m anthropic/claude-haiku-4.5 -y
```

`harbor` is also usable standalone (`pipx install harbor`; add
`pipx inject harbor daytona` for the `--env daytona` path). For raw
`harbor run`, `.env` is not auto-loaded:

```bash
set -a; source .env; set +a
# or use direnv: echo 'dotenv' > .envrc && direnv allow
```
