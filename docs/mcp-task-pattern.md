# Task pattern: MCP and skill variants

How we wire an auth'd remote MCP or a skill into a Harbor task. The same task dir backs both variants — the tool choice lives in the job config, not `task.toml`.

## The auth blocker

Harbor's `MCPServerConfig` accepts `name | transport | url | command | args`. **No `headers`, no `env`.** Unsupported fields are dropped on purpose. So you cannot declare an `Authorization: Bearer <TOKEN>` remote MCP. Confirmed against `src/harbor/models/task/config.py` + PR #1675.

## The workaround: stdio wrapper

- Declare a stdio MCP whose `command` is a wrapper script.
- Wrapper runs `mcp-remote` (npm proxy), which speaks stdio locally and forwards to the remote streamable-http endpoint with an injected `Authorization` header.
- Token reaches the container via `[environment.env]` in `task.toml`, which IS supported by Harbor and forwards from host `os.environ`.

## File layout

```
tasks/<name>/
  task.toml                  # env passthrough only; no MCP block
  instruction.md             # task only - no mention of tool variant
  environment/
    Dockerfile               # node:22-bookworm + `npm install -g mcp-remote apify-cli`
    apify-mcp-proxy.sh       # the wrapper (see template below)
  tests/
    test.sh, check.py        # Reward Kit verifier (see below)
  solution/solve.sh

skills/<name>/
  SKILL.md                   # Anthropic skill format: frontmatter + body

integrations/<vendor>-<variant>/
  integration.yaml           # name, eval_variant, mcp_servers, skills
  instruction.md             # auto-discovered, appended via extra_instruction_paths

configs/
  <task>-<harness>-<model>-<variant>-eval.yaml   # RunConfig: integration: <vendor>-<variant>
```

## task.toml snippet

Only per-task overrides (timeouts, optional verifier env). No `[[environment.mcp_servers]]`, no token passthrough, no resource block - those are hoisted to the integration / `defaults.py`.

```toml
version = "1.0"

[verifier]
timeout_sec = 60.0

[agent]
timeout_sec = 180.0
```

Token passthrough lives on the integration:

```yaml
# integrations/apify-mcp/integration.yaml
environment_env:
  APIFY_TOKEN: ${APIFY_TOKEN}        # resolved against host env at job build time
```

## Integration: pick the tool variant

The integration decides MCP vs CLI vs skill. `instruction.md` in the task stays tool-agnostic; the integration's `instruction.md` tells the agent which tool to use. The RunConfig references the integration by name.

MCP variant (`integrations/apify-mcp/integration.yaml`):

```yaml
name: apify-mcp
eval_variant: mcp
mcp_servers:
  - name: apify
    transport: stdio
    command: /usr/local/bin/apify-mcp-proxy
    args: []
skills: []
environment_env:
  APIFY_TOKEN: ${APIFY_TOKEN}
```

Skill variant (Harbor uploads the host dir into `/harbor/skills/<name>/` at trial start, then copies into each harness's skill dir: `~/.claude/skills/`, `~/.config/opencode/skills/`, `$HOME/.agents/skills/` for claude-code, opencode, codex respectively):

```yaml
name: apify-skill
eval_variant: skill
mcp_servers: []
# skills/<name>/SKILL.md under the integration dir is auto-discovered
```

`job_builder` fans `mcp_servers` and `skills` into every agent in the RunConfig and appends the integration's `instruction.md` via the job-level `extra_instruction_paths` field. Each instruction file is appended to the task's `instruction.md` with `\n\n` separators (`src/harbor/models/task/task.py:181`).

Harbor merges `task.config.environment.mcp_servers` with `agent.mcp_servers` by name (last wins). There's no way to disable a task-level MCP from the yaml, which is why the task no longer declares one. See `src/harbor/trial/trial.py:641`.

## Wrapper template

```bash
#!/bin/bash
# Stdio shim for https://mcp.apify.com/. Harbor's MCPServerConfig has no
# `headers` field, so we can't declare an auth'd remote MCP directly - we
# declare stdio + this wrapper instead.
set -eu
: "${APIFY_TOKEN:?APIFY_TOKEN env var is required}"
mcp-remote https://mcp.apify.com/ --header "Authorization: Bearer $APIFY_TOKEN" \
  2> >(sed -E "s/apify_api_[A-Za-z0-9]+/apify_api_REDACTED/g" >&2)
```

The `sed` is not cosmetic. `mcp-remote` logs the raw `Authorization` header to stderr on startup; that stream is captured by claude-code and persisted to `jobs/.../trajectory.json`. We had two token leaks before adding the filter. Match the regex to whatever token format the vendor uses.

## Sandbox choice

`--env docker` only, today. **Daytona's free/Hobby tiers enforce an outbound allowlist** that doesn't include `*.apify.com` (and likely won't include `*.linear.app`, `*.notion.com`). Symptom: TLS handshake stalls, MCP "failed", curl returns empty body. Tier 3 ($500 top-up) gets full internet, or email `support@daytona.io` to add a domain. See `docs/harbor-constraints.md` for details.

## Verifier design rule

**The expected answer must require an actual tool call**, not a name the agent can guess from the prompt. We tried a "list connected MCP names → /app/mcps.txt" task and the agent passed by writing `apify\n` from the init message alone, with `connected: []`. Use a stable opaque value the API returns (e.g., `moJRLRc85AitArpNN` for `apify/web-scraper`).

## Verifier pattern (Reward Kit)

`tests/test.sh` is a one-liner that runs [Reward Kit](https://www.harborframework.com/docs/rewardkit); it discovers criteria in `/tests/`, evaluates them against the workspace at `/app`, and writes `/logs/verifier/reward.json`. No pytest, no manual reward file.

```bash
# tests/test.sh
#!/bin/bash
set -e
curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh
source $HOME/.local/bin/env
uvx --from harbor-rewardkit==0.1.4 rewardkit /tests
```

Built-in helper (substring/existence check, permissive):
```python
# tests/check.py
import rewardkit as rk
rk.file_contains("mcps.txt", "apify")
```

Custom criterion (exact match, strict — use when a built-in would be too permissive):
```python
# tests/check.py
from pathlib import Path
from rewardkit import criterion

@criterion
def actor_id_matches(workspace: Path) -> bool:
    return (workspace / "actor_id.txt").read_text().strip() == "moJRLRc85AitArpNN"
```

## Adapt for another vendor

1. Copy `tasks/apify-fetch-actor-id/` to `tasks/<vendor>-<task>/`.
2. In `environment/<vendor>-mcp-proxy.sh`: change the URL, the env var name, and the redaction regex.
3. In `task.toml`: swap the env var (no MCP block).
4. In `.env.example` + `.env`: add the new token.
5. Rewrite `instruction.md` (task only, no tool wording) and `tests/check.py` for the new vendor.
6. Create `integrations/<vendor>-<variant>/` with `integration.yaml` (mcp_servers and/or skills, `eval_variant`) and `instruction.md` (tool wording).
7. Add a RunConfig under `configs/` with `integration: <vendor>-<variant>` and `tasks: - path: tasks/<vendor>-<task>`.

## Existing tasks

- `tasks/apify-fetch-actor-id/` - real Apify call, not gameable. MCP + skill variants both wired.
- `tasks/apify-scrape-page/` - runs an Actor and reads its dataset. MCP + skill variants both wired.
- `tasks/apify-mcp-connected/` - connection smoke, gameable. MCP-only (no skill equivalent makes sense).
