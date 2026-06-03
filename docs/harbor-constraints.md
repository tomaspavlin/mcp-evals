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

- `MCPServerConfig` schema is `name | transport | url | command | args` - **no `headers` field**. Source: `harbor/models/task/config.py`.
- Remote MCPs that require `Authorization: Bearer <TOKEN>` (Apify, hosted Linear/Notion, GitHub Copilot MCP) **cannot be authed declaratively in `task.toml` today**.
- Three workarounds, in order of effort:
  1. **Stdio equivalent + env var.** Most vendor MCPs ship a `npx -y …` / `uvx …` package alongside their hosted HTTP endpoint. The stdio version takes the token via env var. Often functionally identical to the remote (same backend). Single-container, cloud-compatible. *Caveat:* you're not testing the literal hosted endpoint.
  2. **Runtime registration in the agent.** Have a setup step write the agent's native MCP config (e.g. `~/.claude.json`) directly with headers. Bypasses Harbor's MCP config. Hackier but works for any agent.
  3. **Patch Harbor.** Add `headers: dict[str, str]` to `MCPServerConfig` and update each agent's MCP serialization. ~50 LoC + tests. Worth upstreaming.

## Multi-container & cloud (only matters if/when we add mock MCPs later)

If we later want to add deterministic mock MCPs (own container with seeded data, sidecar via Compose) the constraints kick in:

- Multi-container tasks (`docker-compose.yaml`) **only work with `--env docker` (local execution)**.
- Cloud sandbox providers currently only support single-Dockerfile environments. Harbor team says multi-container cloud is in progress, not shipped.
- Not a blocker for our primary goal (remote prod MCP testing).

## OpenRouter via Anthropic-compat (claude-code) - BASE_URL gotcha

When routing claude-code through OpenRouter, set `ANTHROPIC_BASE_URL=https://openrouter.ai/api` **without** the `/v1` suffix. The Anthropic SDK (and claude-code on top of it) appends `/v1/messages` to the base - using `https://openrouter.ai/api/v1` produces a double-`/v1` path → 404 model_not_found. OpenAI-compat for codex is the opposite: `OPENAI_BASE_URL=https://openrouter.ai/api/v1` (SDK appends only `/chat/completions`).

Model slugs on OpenRouter use **dots, not hyphens**: `anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-4.5`. Verified at https://openrouter.ai/api/v1/models.

## Cloud sandbox gotchas

- **E2B `--env e2b`** - Harbor hardcodes `timeout=86_400` (24h) when creating the E2B sandbox (`harbor/environments/e2b.py:198`). E2B's free/Hobby tier caps sandbox lifetime at 1 hour, so every request gets rejected with `400: Timeout cannot be greater than 1 hours`. Workarounds: upgrade E2B to Pro, or patch the line to `3_600`.
- **Daytona `--env daytona`** - needs `DAYTONA_API_KEY` (or `DAYTONA_JWT_TOKEN` + `DAYTONA_ORGANIZATION_ID`). Optional `DAYTONA_TARGET`. No hardcoded sandbox-creation timeout. Source: `harbor/environments/daytona/environment.py:89-96`.
- **All cloud providers ship as optional install extras** - `pipx inject harbor e2b` / `daytona` / `modal` etc. Without the matching extra, `--env <provider>` errors at runtime.

## Closest existing template

- **`harbor-cookbook/harbor_cookbook/recipes/mcp-tools/`** - the canonical MCP-using task template. See [`./harbor-task-example.md`](./harbor-task-example.md) for the annotated walkthrough.
- Also relevant: `harbor/examples/tasks/hello-mcp/`, `harbor-cookbook/recipes/skills/` (Harbor has first-class "skills" support as a comparison axis).
- Terminal-Bench's original 241 tasks predate MCP support - not useful as templates.
