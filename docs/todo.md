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

Workaround: `src/mcp_evals/_patches/integration_setup_script.py` monkey-patches `Trial._prepare` to exec a connector-cell-provided `setup.sh` after env start + healthcheck + skill upload, before agent setup. Non-zero exit fails the trial loudly. Used by `connectors/apify/cli/setup.sh` and `connectors/apify/skill/setup.sh` to pre-run `apify login --token "$APIFY_TOKEN"`.

Upstream ask: add `EnvironmentConfig.setup_script` (or expose `agent_environment` on the hook event). Remove the patch and `ConnectorCell.setup_script_path` plumbing once landed.

## E2B sandbox timeout hardcoded to 24h (Harbor gap)

Harbor's `E2BEnvironment._create_sandbox` (`harbor/environments/e2b.py:198`) calls `AsyncSandbox.create(timeout=86_400)` with no override. E2B free plan caps sandbox lifetime at 1 h, so creation fails on a free key.

Workaround: `src/mcp_evals/_patches/e2b_timeout.py` monkey-patches `AsyncSandbox.create` to clamp `timeout` to 3600 s. Remove the patch (and its import in `src/mcp_evals/__init__.py`) when harbor exposes a `sandbox_timeout_secs` arg like `modal.py:883` does, or when we move to E2B paid.

## Codex via OpenRouter: Responses API wss 404 noise

Codex CLI tries `wss://openrouter.ai/api/v1/responses` first; OpenRouter doesn't expose that WebSocket endpoint, so codex logs 5x `404 Not Found` before falling back to HTTP Responses, which succeeds. Cosmetic but spams trial logs.

No clean fix without either real OpenAI auth (bypass OpenRouter) or OpenRouter adding ws Responses support. Document and ignore for now.

## Shared docker base image for MCP proxies (DONE)

**Status (2026-06-15):** Done as part of the connector/channel refactor. `images/base/Dockerfile` installs apify-cli + gh CLI + mcp-remote + @apify/mcpc + copies both proxy scripts; `materialize_environment` (`src/mcp_evals/connectors/materialize.py`) copies that dir unchanged into every `tasks/<task>/environment/`. Per-task Dockerfiles are gone.

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

## Subagent trajectories invisible to viewer + verifier

Diagnosed 2026-06-15 from Group D of `docs/agent-integration-matrix.md`. Claude-code's `Agent` tool spawns a subagent whose tool calls (Bash, WebFetch, MCP, more nested `Agent`s) are logged separately to `<trial>/agent/sessions/projects/-app/<session>/subagents/agent-<id>.jsonl` + `.meta.json`. None of our downstream consumers read them:

- **ATIF builder excludes them.** `harbor/agents/installed/claude_code.py:182` filters out any session JSONL whose path contains `subagents` when discovering the primary session, so `agent/trajectory.json` records the parent's `Agent` tool call as one opaque step. Subagent tool calls never enter ATIF.
- **`harbor view jobs` doesn't load them.** `harbor/src/harbor/viewer/server.py:1732` only reads `agent/trajectory.json`.
- **Our dashboard doesn't load them.** `apps/dashboard/app.py:71,157,362` only reads `agent/trajectory.json`.
- **Task verifiers don't load them.** `tasks/*/tests/check.py` calls `collect_tool_calls(load_trajectory("/logs/agent/trajectory.json"))`, so `used_expected_channel` is blind to anything inside an `Agent` call - a delegation pattern that would route MCP through a subagent would falsely score 0 on the channel criterion.

Group D showed sonnet's failure mode (subagents fall back to shell because claude-code doesn't propagate MCP servers down). The same blind spot would also hide a *successful* MCP call made from inside a subagent on any agent that does propagate MCP downward.

Fix direction (ordered by value):
1. **Flatten subagent tool calls into ATIF.** In the claude-code adapter, walk `sessions/.../subagents/*.jsonl` (using `.meta.json` to thread parent/child + name the subagent) and emit their tool_use events as additional steps under the parent `Agent` step, e.g. via a nested `subagent_trajectory_ref` on the parent `Observation.results[]` (the ATIF schema already has the field - `harbor/agents/installed/claude_code.py:275,325` currently set it to `None`). Once ATIF carries them, both viewers and verifier "just work".
2. **Or, until (1) lands, walk the sessions dir from the verifier.** `tasks/*/tests/check.py` could scan `/logs/agent/sessions/projects/*/subagents/*.jsonl` and append tool uses to `_tool_calls()`. Faster to ship; doesn't help the viewers.
3. **Viewer: render subagent steps as collapsible nested groups** under the parent `Agent` call (in `harbor view jobs` and `apps/dashboard/`) once ATIF carries the refs.

Upstream ask: land (1) in harbor's claude-code adapter so all downstream consumers benefit. Mark Group D and any future "agent delegated to subagent" cells as untrusted on the channel criterion until then.

## E2B template collision across concurrent same-task integration jobs (FIXED via shared base image)

**Status (2026-06-15):** Race A is gone. The connector/channel refactor moved every task onto a single shared `images/base/Dockerfile` (all CLIs + MCP proxies pre-installed). `materialize_environment` now copies the same dir into every `tasks/<task>/environment/` regardless of channel, so the dirhash is identical across channel sweeps and the wrong-image race cannot happen. Race B (e2b cold-build thundering herd on a not-yet-cached template) still exists, but is independent of channel selection; it only kicks in for parallel cold builds of the same alias. The "don't run same-task configs in parallel" warnings have been removed from `README.md` and `AGENTS.md`. Race-B notes below are kept for upstream reference.

---

### Historical: E2B template collision across concurrent same-task integration jobs (our bug + Harbor gap)

Diagnosed 2026-06-15 from the `apify-fetch-actor-id` matrix (Group B in `docs/agent-integration-matrix.md`). Two distinct races; the first silently corrupts results, the second is flaky infra noise.

### Race A: shared materialize path → wrong image built (correctness bug, ours)

`materialize_environment` (`src/mcp_evals/integrations/materialize.py:26`) copies the integration's `environment/` into the **task-keyed, shared** path `tasks/<task>/environment/`. The e2b template name is computed lazily at trial-start as `<environment_name>__<dirhash(environment/)>[:8]` (`harbor/environments/definition.py:75`, `e2b.py:84`), where `environment_name` is the **task** name. So nothing in the template identity distinguishes integrations except the dirhash of that shared dir.

When ≥2 integration jobs for the same task run concurrently (the matrix launched all 4 apify configs within ~4 s), they materialize into and clobber the same `tasks/<task>/environment/`. Whichever Dockerfile is on disk when a trial reaches template-hash time wins. In the 2026-06-14 run the `apify-mcpc` trials hashed+built the **apify-cli** image (`apify-fetch-actor-id__d0745b9e`): `mcpc` was never installed, every `mcpc …` returned exit 127, and agents silently fell back to `curl https://api.apify.com`. The verifier channel check `cmd.startswith("mcpc ")` (`tasks/apify-fetch-actor-id/tests/check.py:58`) counts the *failed attempt* as success, so sonnet/codex scored `used_expected_channel(mcpc)=1.0` despite never running mcpc. **The entire apify-mcpc column was a false pass.**

Note `apify-cli` and `apify-skill` ship byte-identical Dockerfiles (`apify-cli@1.6.2`) → identical dirhash → they legitimately share a template; integration name must therefore enter the template **name/hash**, not just the materialize path, to be fully collision-proof.

Fix (ours): isolate materialize into a per-job working copy of the task dir (disjoint targets), AND fold the integration name into `environment_name`/the template alias so identical-Dockerfile integrations don't collide either. Add a `setup.sh` smoke assert (`command -v mcpc || exit 1`) per integration so a wrong image aborts loudly instead of passing via fallback. Harden `used_expected_channel` to require a *successful* channel call (inspect tool_result for exit 127 / "command not found"), not just a command prefix.

### Race B: cold-build thundering herd on one alias (Harbor gap)

`E2BEnvironment.start` (`harbor/environments/e2b.py:219`) is `if not await self._does_template_exist(): await self._create_template()` with **no build lock**. When several trials in one job start on a not-yet-cached template, they all see "doesn't exist" and build the same alias concurrently → e2b rejects the racers with `BuildException: 400: build is not in waiting state` / `build was cancelled` (the opencode failures in Group B). `apple_container.py:31` already serializes this with `_image_build_locks: dict[str, asyncio.Lock]` keyed by `environment_name`; e2b has no equivalent. This can hit even a **solo** job with `-n >1` on a cold template; once one trial caches the alias the rest reuse it warm. The e2b-parallel memory ("rerun SandboxException trials solo") is a symptom of this.

Fix: add an e2b build lock mirroring `apple_container`, or pre-warm the template (build once before fanning out trials). Upstream ask: port the apple_container build-lock pattern into the e2b backend.

### Stopgap until fixed

Run integration jobs for the same task **serially** (one config at a time, don't launch the matrix configs concurrently). Race A vanishes (distinct Dockerfile content → distinct alias → correct image each time); Race B is reduced to the cold-build-within-one-job case, mitigated by `-n 1` or rerunning `BuildException` trials solo.

The "do not run same-task integrations in parallel" warnings in `README.md` (Known limitations) and `AGENTS.md` (Configs section) document this stopgap. **Once race A is fixed, remove both warnings** (and drop this stopgap subsection).
