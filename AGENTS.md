# mcp-evals

## Goal

Evaluate MCP servers. The project serves two purposes:

1. **MCP server development** - build new MCP servers and evaluate them.
2. **Compare existing MCP servers vs their CLI / API / skill alternatives** - measure whether MCP wrapping actually helps an agent vs giving it the underlying tool directly.

Evaluations run across different LLMs and agent harnesses. Starting with: **claude-code, codex, opencode**.

## Framework

Built on **Harbor** ([docs](https://www.harborframework.com/docs), [gh](https://github.com/harbor-framework/harbor)), the same framework behind [tbench.ai](https://www.tbench.ai/). **Reuse Harbor primitives - do not reimplement.** If you find yourself writing infrastructure that looks like task definition, sandboxing, agent install, verifier, or trial orchestration, stop and find the Harbor abstraction first.

## Targets

MCP servers to evaluate:
- Apify - https://mcp.apify.com/
- GitHub
- Linear
- Notion

Start with **read-only tool calls** for simplicity. Test production / staging remote MCPs directly - no need to run them locally.

## Metrics

- Task success rate
- Token / cost efficiency
- Agent execution traces (for debugging)
- Anything else useful as we go

## CLI

`mcp-evals run` is the primary entrypoint. Built on Harbor's `Job` API (`src/mcp_evals/`); custom Typer CLI mirroring harbor flag names + `--integration`. Auto-loads `.env` from cwd.

From a config:
```bash
uv run mcp-evals run -c configs/<name>.yaml -y
```

When the user asks you to run a test, **prefer flag-driven mode over writing a config file** — fewer tokens, no temp yamls to clean up. If a config file is genuinely needed, use the new `RunConfig` schema (`integration:` + `tasks`/`datasets` + `agents`), never the old harbor `JobConfig` shape.

Ad-hoc via flags (no config file):
```bash
uv run mcp-evals run --integration apify-mcp -a oracle -t tasks/apify-fetch-actor-id -y
uv run mcp-evals run --integration apify-mcp -a oracle \
  --dataset-path tasks --task-name 'apify-*' --exclude-task-name apify-mcp-connected -y
```

Flags: `--integration NAME`, `-a/--agent NAME`, `-m/--model MODEL` (omit for oracle), `-t/--task PATH` (repeatable), `-p/--dataset-path PATH`, `--task-name GLOB` (repeatable), `--exclude-task-name GLOB` (repeatable), `--job-name`, `-k/--n-attempts`, `-n/--n-concurrent`, `--env-file`, `-y`. Each flag overrides whatever's in `-c`.

## Configs

New schema (our `RunConfig`, ~8 lines): `job_name`, `integration`, `tasks` / `datasets`, `agents` (just `name` + `model_name` + optional `kwargs`). Everything else - environment, mcp_servers, skills, instruction append, `EVAL_VARIANT`, default agent kwargs, concurrency - comes from the named integration + `src/mcp_evals/defaults.py`. See `configs/apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml` for the canonical example.

Naming: `<dataset>-<harness>-<model>-<tool>-<purpose>.yaml`; `<tool>` is `mcp`, `cli`, `skill`, or `mcpc` (shell-driven MCP via [`@apify/mcpc`](https://github.com/apify/mcpc)); `<purpose>` is `eval`. Keep secrets in `.env`, never in yaml.

If a run fails with `FileExistsError` (job dir already exists), remove `jobs/<job-name>/` and rerun.

## Integrations

`integrations/<name>/` bundles the (MCP servers | skills | instruction append | EVAL_VARIANT) tuple that distinguishes a tool-access strategy for the same underlying task. Files: `integration.yaml` + sibling `instruction.md` + optional `skills/<skill-name>/SKILL.md` (all auto-discovered by the loader). To add an integration, drop a new directory; reference it via `integration:` in a `RunConfig`.

## Harbor patches

`src/mcp_evals/_patches/` holds runtime monkey-patches for harbor upstream gaps (codex MCP env propagation, E2B free-tier sandbox timeout). Prefer upstreaming over patching when feasible.

## Dashboard

Custom Streamlit app at `apps/dashboard/` for project-specific plots over `jobs/`. Reads via Harbor's `JobScanner` so schema parsing stays in sync. Complements `harbor view jobs`, does not replace it. See `apps/dashboard/README.md` for setup and run instructions.

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
