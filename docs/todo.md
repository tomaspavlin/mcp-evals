# TODO

## Expected-tool-set metrics (deferred)

Per-task, per-channel declaration of which tools should suffice, e.g. in `task.toml`:

```toml
[metadata.expected_tools]
mcp = ["fetch-actor-details"]
cli = ["apify actors info", "apify api"]
```

Harbor's task config accepts free-form `[metadata]`. Computed post-hoc in `src/mcp_evals/metrics.py` (no verifier changes): `unexpected_channel_tools` (channel calls outside the set) and `used_only_expected_tools` (bool). Diagnoses tool naming/description quality (agent picked the wrong tool first) and granularity. Deliberately observational, not a reward criterion: tasks can have valid alternative paths.

## channel_output_chars undercounts truncated opencode outputs

Opencode replaces large tool outputs with a stub in the session log ("...output truncated... Full output saved to: /root/.local/share/opencode/tool-output/..."), and the ATIF observation records the stub. `channel_output_chars` therefore measures what reached the model context (arguably the more relevant number) but undercounts what the surface actually returned; cli/mcpc bash outputs are truncated most often, MCP results typically pass through whole. If we ever need the raw size, the full outputs sit in the sandbox under opencode's tool-output dir and would have to be downloaded as artifacts before teardown. Detect the stub marker in metrics.py and flag the call (e.g. `truncated: true` in per_call) as a first step.

## Codex trajectory: no per-step token metrics (Harbor gap)

Harbor's codex adapter converts the codex session log to ATIF with `metrics: null` on every step; only `final_metrics` carries token totals (the per-turn data exists at the source, see `last_token_usage` surviving in `final_metrics.extra`). Consequences: `prompt_baseline_tokens` is None for codex and the dashboard's cumulative-token timeline is empty for codex trials. Trial-level totals (tokens, cost) are unaffected. Fix upstream in harbor's codex trajectory conversion rather than in `_patches/`.

## Codex agent: MCP env not propagated (Harbor gap)

Harbor's codex agent (`harbor/agents/installed/codex.py`, `_build_register_mcp_servers_command`) writes only `command`/`url` to `$CODEX_HOME/config.toml`, never `env`. Codex CLI does support `env = { KEY = "value" }` per [codex config reference](https://developers.openai.com/codex/config-reference), so MCP child processes never receive secrets we declared via task `[environment.env]`.

Workaround: `src/mcp_evals/_patches/codex_mcp_env.py` monkey-patches `_build_register_mcp_servers_command` to emit an `env = { KEY = "${KEY}" }` block per MCP server, sourced from a `MCP_SERVER_ENV` mapping. Heredoc with unquoted delimiter so shell substitution happens at exec time in docker (same pattern codex.py:766-770 uses for `OPENAI_BASE_URL`). Remove patch and import in `src/mcp_evals/__init__.py` once harbor lands the fix. Upstream PR still TODO.

## Codex agent: MCP tool-name prefix stripped (verifier convention gap)

`tasks/apify-fetch-actor-id/tests/check.py` originally matched `function_name.startswith("apify_")` to detect MCP usage. Claude-code/opencode keep the server prefix (`apify_fetch-actor-details`); codex strips it and normalizes hyphens to underscores (`fetch_actor_details`). Fixed by switching the channel detector to an allowlist of normalized apify MCP tool names (`APIFY_MCP_TOOLS`). Extend `APIFY_MCP_TOOLS` when surfacing new apify tools in the eval.

## No sandbox setup-script hook (Harbor gap)

Harbor exposes `Job.add_hook(TrialEvent.AGENT_START, ...)` but the `TrialHookEvent` payload (`harbor/trial/hooks.py:21`) carries only `event`, `trial_id`, `task_name`, `config`, `result` - not the live `Trial` or `agent_environment`. So a hook callback can't `exec()` into the running sandbox. `EnvironmentConfig` also has no `setup_script` field, and single-step tasks have no equivalent of multi-step's `steps/<name>/workdir/setup.sh`.

Workaround: `src/mcp_evals/_patches/integration_setup_script.py` monkey-patches `Trial._prepare` to exec an integration-provided `setup.sh` after env start + healthcheck + skill upload, before agent setup. Non-zero exit fails the trial loudly. Used by `integrations/apify-cli/setup.sh` and `integrations/apify-skill/setup.sh` to pre-run `apify login --token "$APIFY_TOKEN"`.

Upstream ask: add `EnvironmentConfig.setup_script` (or expose `agent_environment` on the hook event). Remove the patch and `Integration.setup_script_path` plumbing once landed.

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
