# TODO

## Codex agent: MCP env not propagated (Harbor gap)

Harbor's codex agent (`harbor/agents/installed/codex.py`, `_build_register_mcp_servers_command`) writes only `command`/`url` to `$CODEX_HOME/config.toml`, never `env`. Codex CLI does support `env = { KEY = "value" }` per [codex config reference](https://developers.openai.com/codex/config-reference), so MCP child processes never receive secrets we declared via task `[environment.env]`.

Symptom on `apify-fetch-actor-id` with codex: MCP startup fails with `Broken pipe (os error 32)` because `apify-mcp-proxy.sh` exits on `${APIFY_TOKEN:?...}`. See `jobs/apify-fetch-actor-id-codex-gpt5mini-eval/`.

Fix: fork harbor at `../harbor`, extend `_build_register_mcp_servers_command` to emit an `env = { ... }` block from `server.env`. Install harbor from the clone. Upstream PR.

## E2B sandbox timeout hardcoded to 24h (Harbor gap)

Harbor's `E2BEnvironment._create_sandbox` (`harbor/environments/e2b.py:198`) calls `AsyncSandbox.create(timeout=86_400)` with no override. E2B free plan caps sandbox lifetime at 1 h, so creation fails on a free key.

Workaround: `src/mcp_evals/_patches/e2b_timeout.py` monkey-patches `AsyncSandbox.create` to clamp `timeout` to 3600 s. Remove the patch (and its import in `src/mcp_evals/__init__.py`) when harbor exposes a `sandbox_timeout_secs` arg like `modal.py:883` does, or when we move to E2B paid.

## Codex via OpenRouter: Responses API wss 404 noise

Codex CLI tries `wss://openrouter.ai/api/v1/responses` first; OpenRouter doesn't expose that WebSocket endpoint, so codex logs 5x `404 Not Found` before falling back to HTTP Responses, which succeeds. Cosmetic but spams trial logs.

No clean fix without either real OpenAI auth (bypass OpenRouter) or OpenRouter adding ws Responses support. Document and ignore for now.

## Shared docker base image for MCP proxies

Today each apify task duplicates `apify-mcp-proxy.sh` and re-installs `mcp-remote` in its Dockerfile (`tasks/apify-*/environment/`). The proxy scripts across the three apify tasks are byte-identical.

Plan: build one `mcp-evals-apify:base` image with node + `mcp-remote` + proxy baked in. Per-task Dockerfiles become a single `FROM mcp-evals-apify:base`. Proxy source moves to `integrations/apify-mcp/proxy.sh` + `integrations/apify-mcp/Dockerfile.base`, built by a `mcp-evals build-integration apify-mcp` subcommand. Same pattern for github / linear / notion MCPs.

Deferred until after `docs/python-cli-migration.md` lands — needs the CLI in place first.

## Output metrics & visualisation

Data we already collect per trial (in `jobs/<job>/<trial>/`):

- `result.json` - totals: `n_input_tokens`, `n_cache_tokens`, `n_output_tokens`, `cost_usd`, reward, phase timings (`environment_setup`, `agent_setup`, `agent_execution`, `verifier`).
- `agent/trajectory.json` - per-step `timestamp`, `prompt_tokens`, `completion_tokens`, `cached_tokens`, `cost_usd`, `tool_calls[].function_name`, `observation.results[].content`.
- `verifier/reward-details.json` - per-trial failure breakdown.
- `job.log`, `trial.log` - error patterns.

### Charts to build

- **Cost-per-success (primary)** - grouped bar by task, grouped by approach (MCP / CLI / skill), faceted per harness+model. Bar = `mean_cost / success_rate`. Collapses efficiency + outcome into one number, makes the MCP-vs-alternative comparison primary.
- **Token mix stacked bar** - mean `input / cache / output` per config. Diagnoses *why* one approach is cheaper (cache hits? fewer turns?).
- **Success-rate heatmap** - rows = task, cols = harness+model, one heatmap per approach. Quick scan for viable combinations.
- **Cumulative tokens over time (per run)** - X = step timestamp (or elapsed s), Y = cumulative `prompt_tokens` or `cost`. One line per trial, color = harness+model, linestyle = approach. Annotate points with `function_name` to surface where tokens balloon.
- **Tool-call mix** - bar of which tools the agent reached for, per approach. Answers "did the MCP wrapper actually get used, or did the agent fall back to shell?"
- **Tokens-per-tool-call** - observation size (`len(observation.results[].content)`) per tool. Context bloat is where MCP usually loses to CLI.
- **Phase duration breakdown** - stacked bar of `environment_setup` / `agent_setup` / `agent_execution` / `verifier`. Separates MCP cold-start overhead from agent thinking time.
- **Failure-mode bar** - aggregate `trial.log` / `verifier/reward-details.json` into categories (timeout, auth, tool error, wrong answer).

### Skip for now

- Cost-vs-success scatter per trial - too few trials per cell (3) to look meaningful.
- Time-series across runs - runs aren't ordered meaningfully yet.
