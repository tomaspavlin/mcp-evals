# mcp-evals

## Goal

Evaluate MCP servers. The project serves two purposes:

1. **MCP server development** - build new MCP servers and evaluate them.
2. **Compare existing MCP servers vs their CLI / API / skill alternatives** - measure whether MCP wrapping actually helps an agent vs giving it the underlying tool directly.

Evaluations run across different LLMs and agent harnesses. Starting with: **claude-code, codex, opencode**.

## Framework

Built on **Harbor** ([docs](https://www.harborframework.com/docs), [gh](https://github.com/harbor-framework/harbor)), the same framework behind [tbench.ai](https://www.tbench.ai/). **Reuse Harbor primitives - do not reimplement.** If you find yourself writing infrastructure that looks like task definition, sandboxing, agent install, verifier, or trial orchestration, stop and find the Harbor abstraction first.

## Connectors

Third-party services we evaluate (project term: **connector**):
- Apify - https://mcp.apify.com/
- GitHub
- Linear
- Notion

Each connector has cells for the different **channels** the agent can reach it through (mcp, cli, mcpc, skill). Multi-connector tasks are supported: one task can use apify + github at the same time. Start with **read-only tool calls** for simplicity. Test production / staging remote MCPs directly - no need to run them locally.

## Metrics

- Task success rate
- Token / cost efficiency
- Agent execution traces (for debugging)
- Anything else useful as we go

## CLI

`mcp-evals run` is the primary entrypoint. Built on Harbor's `Job` API (`src/mcp_evals/`); custom Typer CLI mirroring harbor flag names + `--channel`. Auto-loads `.env` from cwd.

From a config:
```bash
uv run mcp-evals run -c configs/<name>.yaml -y
```

When the user asks you to run a test, **prefer flag-driven mode over writing a config file** - fewer tokens, no temp yamls to clean up. If a config file is genuinely needed, use the `RunConfig` schema (`channel:` + optional `connectors:` + `tasks`/`datasets` + `agents`), never the old harbor `JobConfig` shape.

Ad-hoc via flags (no config file):
```bash
# Connectors auto-resolved from [mcp_evals].connectors in each task.toml.
uv run mcp-evals run --channel mcp -a oracle -t tasks/apify-fetch-actor-id -y
uv run mcp-evals run --channel mcp -a oracle \
  --dataset-path tasks --task-name 'apify-*' --exclude-task-name apify-mcp-connected -y

# Explicit connector list (overrides task.toml):
uv run mcp-evals run --channel mcp --connector apify --connector github -a oracle -t tasks/cross-actor-meta-and-repo-meta -y
```

Flags: `--channel {mcp,cli,mcpc,skill}`, `--connector NAME` (repeatable, optional), `--connectors-dir PATH` (default `./connectors`), `-a/--agent NAME`, `-m/--model MODEL` (omit for oracle), `-t/--task PATH` (repeatable), `-p/--dataset-path PATH`, `--task-name GLOB` (repeatable), `--exclude-task-name GLOB` (repeatable), `--job-name`, `-o/--jobs-dir PATH` (default `./jobs`), `-k/--n-attempts`, `-n/--n-concurrent`, `--env {docker,daytona,e2b,...}` (sandbox backend, default e2b), `--env-file`, `-y`. Each flag overrides whatever's in `-c`. Eval definitions can live in an external repo: see "Usage" in `README.md` (covers `--connectors-dir`, `-o/--jobs-dir`, and yaml-relative `skills:` globs).

## Configs

Schema (our `RunConfig`, ~8 lines): `job_name`, `channel` (mcp|cli|mcpc|skill), optional `connectors` (auto-resolved from each task's `[mcp_evals].connectors` when omitted), optional `connector_channels` for hybrid runs, `tasks` / `datasets`, `agents` (just `name` + `model_name` + optional `kwargs`), optional `connectors_dir` / `jobs_dir` for eval definitions living outside this repo. Everything else - environment, mcp_servers, skills, instruction append, verifier env, default agent kwargs, concurrency - comes from the loaded connector cells + `src/mcp_evals/defaults.py`. See `configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml` for the canonical example.

Naming: `<dataset>-<harness>-<model>-<channel>-<purpose>.yaml`; `<channel>` is `mcp`, `cli`, `skill`, or `mcpc` (shell-driven MCP via [`@apify/mcpc`](https://github.com/apify/mcpc)); `<purpose>` is `eval`. Keep secrets in `.env`, never in yaml.

If a run fails with `FileExistsError` (job dir already exists), remove `jobs/<job-name>/` and rerun.

Materialize now uses **one shared base image** (`images/base/Dockerfile`) with every CLI / MCP proxy installed, copied unchanged into each task's `environment/`. Channel selection happens at runtime (which `mcp_servers`, instruction appends, and setup scripts the agent gets). Same Dockerfile across every run = stable `dirhash` = the sandbox template cache stays hot. The old per-integration Dockerfile collision (different integrations clobbering each other into `tasks/<task>/environment/` concurrently) no longer applies; same-task channel sweeps can now run in parallel.

## Models

OpenRouter slugs prefixed with `openrouter/`. Always pin a provider via `@preset/<slug>` so prompt caching works across turns - without it OpenRouter re-routes every request and cache hits drop to ~0 (see [docs/harbor-constraints.md](docs/harbor-constraints.md) § OpenRouter prompt caching).

Current models:
- `openrouter/deepseek/deepseek-v4-flash@preset/deepseek-provider-only` - cheap default (~$0.09 / $0.18 per Mtok)
- `openrouter/deepseek/deepseek-v4-pro@preset/deepseek-provider-only` - heavier tier (~$0.435 / $0.87 per Mtok)

Adding a new model: confirm the desired upstream provider serves it at `https://openrouter.ai/<provider>/<model>`, create the matching `@preset/<provider>-only` on OpenRouter, then reference it via the combined `model@preset/slug` syntax.

## Connectors and channels

Tool access is split into two axes:
- **channel** = how the agent reaches a connector: `mcp`, `cli`, `mcpc`, `skill`. Picked per run.
- **connector** = which third-party service: `apify`, `github`, `linear`, `notion`. Picked per task.

Each (connector, channel) lives at `connectors/<connector>/<channel>/`: `cell.yaml` (mcp_servers / env / setup_env / teardown_env) + sibling `instruction.md` + optional `setup.sh` + optional `teardown.sh` + optional `skills/<skill-name>/SKILL.md`. All auto-discovered by the loader. `setup.sh` runs in the sandbox after env start and before the agent, with `setup_env` resolved in scope - use it for pre-auth (e.g. `apify login --token "$APIFY_TOKEN"`) so CLI/skill cells match the implicit auth MCP gets. `teardown.sh` runs after the agent and before artifact collection. Setup failure aborts the trial; teardown failure is logged and swallowed. Neither setup nor teardown env leaks into the agent's persistent env. To add a new connector, drop a new directory under `connectors/`.

Each task declares which connectors it needs via `[mcp_evals].connectors = [...]` in `task.toml`. A run picks one `channel:` (applied to every connector by default) or per-connector overrides via `connector_channels:`. The verifier sees the resulting per-connector channel map via `MCP_EVALS_CHANNELS_JSON` (+ `MCP_EVALS_CHANNEL` shorthand when all connectors share a channel).

## Harbor patches

`src/mcp_evals/_patches/` holds runtime monkey-patches for harbor upstream gaps (codex MCP env propagation, E2B free-tier sandbox timeout, connector-cell `setup.sh` / `teardown.sh` exec in the sandbox). Prefer upstreaming over patching when feasible.

## Metrics

Trajectory-derived metrics (channel/escape call classification, errored calls, `prompt_baseline_tokens`, `tests_passed` from reward-details) live in `src/mcp_evals/metrics.py`: stdlib-only pure functions over ATIF trajectories, importable from any app without harbor. Channel matching is mirrored in `tasks/*/tests/check.py` (verifier containers cannot import the package); keep both in sync. Unit tests in `tests/`, run with `uv run pytest`.

## Dashboard

Custom Streamlit app at `apps/dashboard/` for project-specific plots over `jobs/`. Reads via Harbor's `JobScanner` so schema parsing stays in sync, and loads `src/mcp_evals/metrics.py` by file path for trial metrics. Complements `harbor view jobs`, does not replace it. Launch with `mcp-evals dashboard [JOBS_DIR]` (default `./jobs`; flags `-p/--port`, `--host`, `--no-browser`) - resolves the jobs dir, sets `MCP_EVALS_JOBS_DIR`, and execs streamlit from `apps/dashboard/.venv` (or PATH). See `apps/dashboard/README.md` for setup.

## Project docs

Read these before proposing architecture:

- `docs/harbor-overview.md` - what Harbor is, install, core abstractions
- `docs/harbor-task-example.md` - annotated walkthrough of `harbor-cookbook/recipes/mcp-tools/` (the template we fork)
- `docs/harbor-constraints.md` - discovered facts that constrain design (Python-only runtime, MCP auth header gap, OpenRouter BASE_URL gotcha, cloud sandbox traps)
- `docs/mcp-task-pattern.md` - how we wire an auth'd remote MCP into a Harbor task (stdio wrapper around `mcp-remote`, token via `[environment.env]`, docker-only for now). Fork-this template.
- `docs/todo.md` - open work items: known harness gaps, planned charts, output-metric ideas. Check here before starting new work.

Developer setup (installs, env vars, smoke tests) lives in `README.md`.

## Writing style (applies to all output: docs, code comments, commit messages, chat)

- Be informative, brief, information-dense. No filler, no hedging, no restating the request. One useful line beats three padded ones.
- Do not use em-dashes. Use a regular hyphen, comma, colon, or split the sentence instead.

## Local environment instructions

@AGENTS.local.md
