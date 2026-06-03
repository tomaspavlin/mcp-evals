# Harbor constraints & facts

Things discovered during research that constrain what we can/can't do. Not decisions — those get made as we iterate. Decisions live in commits and conversation.

## Language

- **Harbor is Python-only** (3.12+, PyPI, `uv tool install harbor`). No TS/JS port exists.
- **Built-in agent adapters cover our needs:** claude-code, codex, opencode are all shipped. We do not need to write a custom Python agent.
- **What can be non-Python:**
  - `task.toml`, `instruction.md`, Dockerfiles, `docker-compose.yaml` — declarative
  - Mock MCP servers (any language that speaks MCP)
  - Verifiers — `tests/test.sh` just needs to write `/logs/verifier/reward.txt`; the script behind it can be anything
  - Orchestration (running suites, aggregating results) — Harbor exposes a CLI we can shell out to
- **What forces Python:**
  - Custom agent adapters (we don't need one)
  - Custom Rewardkit scorers / LLM-judge metrics integrated with Rewardkit
  - Patching Harbor itself

## MCP auth

- `MCPServerConfig` schema is `name | transport | url | command | args` — **no `headers` field**.
- Remote MCPs requiring `Authorization: Bearer <TOKEN>` (Apify, hosted Linear, Notion, GitHub Copilot MCP) cannot be authed declaratively in `task.toml`.
- Workarounds:
  1. Use stdio MCP equivalents (`npx -y …`, `uvx …`) and pass tokens via `[environment].env`
  2. Sidecar a local auth-injecting proxy in `docker-compose.yaml`
  3. Patch `MCPServerConfig` in Harbor and upstream a PR (~50 LoC + tests)

## Multi-container & cloud

- Multi-container tasks (sidecar MCPs via `docker-compose.yaml`) **only work with `--env docker` (local execution)**.
- Cloud sandbox providers (Daytona, Modal, E2B) currently only support single-Dockerfile environments. Harbor team says multi-container cloud support is in progress, not shipped.
- Implication: if we want cloud-scale parallel trials, we either wait for cloud multi-container support, or collapse to stdio-only MCPs (no sidecar needed → single container → cloud works).

## Closest existing template

- **`harbor-cookbook/harbor_cookbook/recipes/mcp-tools/`** — the canonical MCP-using task template. See [`./harbor-task-example.md`](./harbor-task-example.md) for the annotated walkthrough.
- Also relevant: `harbor/examples/tasks/hello-mcp/`, `harbor-cookbook/recipes/skills/` (Harbor has first-class "skills" support as a comparison axis).
- Terminal-Bench's original 241 tasks predate MCP support — not useful as templates.
