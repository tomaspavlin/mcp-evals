# Harbor constraints & facts

Things discovered during research that constrain what we can/can't do. Not decisions - those get made as we iterate. Decisions live in commits and conversation.

## Language

- **Harbor is Python-only** (3.12+, PyPI, `uv tool install harbor`). No TS/JS port exists.
- **Built-in agent adapters cover our needs:** claude-code, codex, opencode are all shipped. We do not need to write a custom Python agent.
- **What can be non-Python:**
  - `task.toml`, `instruction.md`, Dockerfiles, `docker-compose.yaml` - declarative
  - Mock MCP servers (any language that speaks MCP)
  - Verifiers - `tests/test.sh` just needs to write `/logs/verifier/reward.txt`; the script behind it can be anything
  - Orchestration (running suites, aggregating results) - Harbor exposes a CLI we can shell out to
- **What forces Python:**
  - Custom agent adapters (we don't need one)
  - Custom Rewardkit scorers / LLM-judge metrics integrated with Rewardkit
  - Patching Harbor itself

## Testing remote production MCPs (our actual use case)

We are evaluating **existing remote MCPs in production/staging** (Apify, hosted GitHub/Linear/Notion MCPs), not running mock MCPs locally. This means:

- **Single container is the default** - only the agent container is needed. It reaches out to `mcp.apify.com`, `mcp.linear.app`, etc. over the public internet.
- **No Docker Compose required.** No sidecar MCPs.
- **Cloud sandboxes (E2B, Daytona, Modal) are viable** - they all support single-Dockerfile tasks.

The real blocker for this use case is **MCP auth**, not multi-container.

## MCP auth - the blocker for remote prod MCPs

- `MCPServerConfig` schema is `name | transport | url | command | args` - **no `headers` field, no `env` field**. Source: `src/harbor/models/task/config.py` (verified June 2026).
- Stronger: Harbor **explicitly drops** unsupported fields with a debug log in `src/harbor/cli/utils.py::load_mcp_servers`. A unit test asserts `{"headers": {"Authorization": "Bearer x"}}` is dropped. This is deliberate. PR #1675 (May 2026) reaffirmed the decision.
- No open issue or PR upstream is requesting headers/auth. No cookbook recipe uses a remote-authed MCP - all `streamable-http` examples point at local FastMCP sidecars.
- Remote MCPs that require `Authorization: Bearer <TOKEN>` (Apify, hosted Linear/Notion, GitHub Copilot MCP) **cannot be authed declaratively in `task.toml` today**.
- Workarounds, in order of effort:
  1. **Stdio equivalent + `[environment.env]` passthrough.** Most vendor MCPs ship a `npx -y …` / `uvx …` package. `MCPServerConfig` has no `env` field, BUT `[environment.env]` in `task.toml` forwards host env vars into the agent's container at runtime (`${VAR}` template, resolved from `os.environ`). Stdio MCP subprocesses inherit env from the agent process, so this is the supported connector. Token never enters the image. Works on docker / daytona / e2b uniformly. *Caveat:* you're not testing the literal hosted endpoint.
  2. **Runtime registration in the agent.** Have a setup step write the agent's native MCP config (e.g. `~/.claude.json`) directly with headers. Bypasses Harbor's MCP config. Hackier but works for any agent.
  3. **Local proxy sidecar.** Run a stdio→http proxy (`mcp-remote` / `mcp-proxy`) inside the container, holding the token, forwarding to the remote MCP. task.toml points `url` at `http://localhost:…`.
  4. **Patch Harbor.** Add `headers: dict[str, str]` to `MCPServerConfig` and update each agent's MCP serialization. ~50 LoC + tests. Worth upstreaming - no upstream interest yet, so we'd lead.

## Multi-container & cloud (only matters if/when we add mock MCPs later)

If we later want to add deterministic mock MCPs (own container with seeded data, sidecar via Compose) the constraints kick in:

- Multi-container tasks (`docker-compose.yaml`) **only work with `--env docker` (local execution)**.
- Cloud sandbox providers currently only support single-Dockerfile environments. Harbor team says multi-container cloud is in progress, not shipped.
- Not a blocker for our primary goal (remote prod MCP testing).

## OpenRouter via Anthropic-compat (claude-code) - BASE_URL gotcha

When routing claude-code through OpenRouter, set `ANTHROPIC_BASE_URL=https://openrouter.ai/api` **without** the `/v1` suffix. The Anthropic SDK (and claude-code on top of it) appends `/v1/messages` to the base - using `https://openrouter.ai/api/v1` produces a double-`/v1` path → 404 model_not_found. OpenAI-compat for codex is the opposite: `OPENAI_BASE_URL=https://openrouter.ai/api/v1` (SDK appends only `/chat/completions`).

Model slugs on OpenRouter use **dots, not hyphens**: `anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.5`. Verified at https://openrouter.ai/api/v1/models.

## OpenRouter prompt caching - pin the provider with a preset

OpenRouter routes each request to whichever upstream provider it picks at that moment. Prompt caches are **per-provider** (DeepSeek's cache, Fireworks' cache, Together's cache are separate), so when consecutive calls land on different providers, the cache miss rate goes to ~100% and we pay full input tokens every turn.

**Fix:** pin the provider via a preset. We created [`@preset/deepseek-provider-only`](https://openrouter.ai/settings/presets) with:

```json
{ "only": ["deepseek"], "allow_fallbacks": false }
```

Same shape for Anthropic models: [`@preset/anthropic-provider-only`](https://openrouter.ai/settings/presets) with `{ "only": ["anthropic"], "allow_fallbacks": false }`. Reference as `openrouter/anthropic/claude-sonnet-4.6@preset/anthropic-provider-only` (slugs use dots, not hyphens).

Reference the preset in the model field using OpenRouter's combined syntax: `<provider>/<model>@preset/<preset-slug>`. All deepseek configs in `configs/` use this form. See `AGENTS.md` § Models for the current model list.

The same problem applies to any provider whose cache we depend on - if you add a new family (Qwen, Llama, etc.) and care about caching, create a matching `@preset/<provider>-only` preset and reference it in the model name.

**Per-model gotcha:** the named provider must actually serve the model. Some OpenRouter models are hosted only by third parties (`deepinfra`, `novita`, `siliconflow`, ...); pinning `@preset/deepseek-provider-only` to such a model 404s with `"No allowed providers are available for the selected model"`. Before adding a new `@preset/<provider>-only` preset to a config, check the model's provider list at `https://openrouter.ai/<provider>/<model>`.

## Cloud sandbox gotchas

- **E2B `--env e2b`** - Harbor hardcodes `timeout=86_400` (24h) when creating the E2B sandbox (`harbor/environments/e2b.py:198`). E2B's free/Hobby tier caps sandbox lifetime at 1 hour, so every request gets rejected with `400: Timeout cannot be greater than 1 hours`. Workarounds: upgrade E2B to Pro, or patch the line to `3_600`.
- **Daytona `--env daytona`** - needs `DAYTONA_API_KEY` (or `DAYTONA_JWT_TOKEN` + `DAYTONA_ORGANIZATION_ID`). Optional `DAYTONA_TARGET`. No hardcoded sandbox-creation timeout. Source: `harbor/environments/daytona/environment.py:89-96`.
- **Daytona outbound network is allowlisted by tier.** Tier 1 (free, email-verified) and Tier 2 ($25 top-up) enforce a global "essential services" allowlist: npm, PyPI, Docker Hub, GitHub, Cloudflare/Fastly, Anthropic, OpenAI, Google AI, DeepSeek, Groq, AWS S3, Vercel, Supabase, Sentry. **Apify (`*.apify.com`) is NOT on the list** - HTTPS to `mcp.apify.com`, `api.apify.com`, `console-backend.apify.com` stalls in TLS handshake (curl empty body, axios socket error, mcp-remote "failed"). Verified 2026-06-03. Source: https://www.daytona.io/docs/en/network-limits/. Matching symptom: https://github.com/daytonaio/daytona/issues/3960. Same TLS-stall pattern in claude-code's own sandbox: https://github.com/anthropics/claude-code/issues/40213.
  - **Implication for this project:** any MCP touching non-allowlisted domains (Apify today; likely Linear, Notion, possibly hosted GitHub) needs `--env docker` OR a Daytona allowlist addition OR Tier 3 ($500 top-up).
  - **Fix paths:** (1) Email support@daytona.io / PR the sandbox-network-whitelist repo for `*.apify.com` etc. (2) Tier 3 = full internet by default. (3) Tier 3's `networkAllowList` is CIDR-only (max 10 IPv4), useless for Cloudflare-fronted hosts.
- **All cloud providers ship as optional install extras** - `pipx inject harbor e2b` / `daytona` / `modal` etc. Without the matching extra, `--env <provider>` errors at runtime.

## `harbor run` operational gotchas

- **No `--env-file` flag.** `harbor run` does not load `.env`. Required vars must be present in the process environment. Export with `set -a; source .env; set +a` (or use direnv) before invoking.
- **Interactive env-var confirmation.** Any task with `[environment.env]` triggers `Tasks in this run will load these from your environment. Proceed? (Y/n)` even when all vars are set. Blocks unattended runs unless stdin is fed (`yes | harbor run ...`).
- **Job lock collision on re-run.** Re-running with the same `job_name` after the config changed errors with `FileExistsError: Job directory jobs/<name> already has a lock.json that does not match the resolved job lock` (`harbor/job.py:584`). This is the replay-safety check. Workaround: `--job-name <fresh>` or remove the prior `jobs/<name>/` dir.

## Trajectory: per-step token counts not populated for codex

`step.metrics` (prompt/completion/cached tokens) is populated for `claude-code` and `opencode` but is `None` on every step for `codex`. Codex's adapter (`harbor/agents/installed/codex.py:540-642`) only parses the rolling `token_count` event stream and rolls it into `final_metrics.total_*`, never attaching usage to individual `Step` objects.

Implication: any metric or chart that wants per-step token attribution is unavailable for codex trials specifically; per-trial aggregates (`agent_result.n_*_tokens`, `trajectory.final_metrics.total_*`) are still correct. Reconstructing per-step usage would require diff'ing successive `token_count` events in the codex adapter - not worth it while we report trial-level numbers.

## Closest existing template

- **`harbor-cookbook/harbor_cookbook/recipes/mcp-tools/`** - the canonical MCP-using task template. See [`./harbor-task-example.md`](./harbor-task-example.md) for the annotated walkthrough.
- Also relevant: `harbor/examples/tasks/hello-mcp/`, `harbor-cookbook/recipes/skills/` (Harbor has first-class "skills" support as a comparison axis).
- Terminal-Bench's original 241 tasks predate MCP support - not useful as templates.
