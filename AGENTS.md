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

## Configs

Job configs live in `configs/*.yaml` (Harbor `JobConfig` schema). Run them with `./scripts/run.sh configs/<name>.yaml` - it sources `.env`, generates a timestamped `--job-name`, and pipes `yes` past the env-confirmation prompt. Extra `harbor run` flags pass through. Naming: `<dataset>-<harness>-<model>-<tool>-<purpose>.yaml` (e.g. `apify-fetch-actor-id-opencode-deepseek-mcp-eval.yaml`); `<tool>` is `mcp` or `skill` for MCP/skill variants of the same task. `<purpose>` is `eval` for new configs; legacy `-smoketest` configs predate this. Keep secrets in `.env`, never in yaml.

Direct `harbor run -c …` works but you must `set -a; source .env; set +a` first (no `--env-file` flag) and pick a fresh `--job-name` after any config change (else `FileExistsError`). `scripts/run.sh` handles both.

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
