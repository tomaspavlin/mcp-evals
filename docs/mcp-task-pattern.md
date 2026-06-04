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

instructions/
  <vendor>-mcp.md            # snippet appended via extra_instruction_paths
  <vendor>-skill.md          # snippet appended via extra_instruction_paths

configs/
  <task>-<harness>-<model>-mcp-eval.yaml      # job: this task + MCP
  <task>-<harness>-<model>-skill-eval.yaml    # job: this task + skill
```

## task.toml snippet

Token passthrough only. No `[[environment.mcp_servers]]` block.

```toml
[environment.env]
APIFY_TOKEN = "${APIFY_TOKEN}"        # required; errors if unset on host
```

## Job config: pick the tool variant

The job yaml decides MCP vs skill and points `extra_instruction_paths` at the matching snippet so the agent gets told which tool to use. `instruction.md` itself stays tool-agnostic.

MCP variant:

```yaml
extra_instruction_paths:
  - instructions/apify-mcp.md

agents:
  - name: opencode
    model_name: openrouter/deepseek/deepseek-chat-v3.1
    mcp_servers:
      - name: apify
        transport: stdio
        command: /usr/local/bin/apify-mcp-proxy
        args: []
```

Skill variant (Harbor uploads the host dir into `/harbor/skills/<name>/` at trial start, then copies into each harness's skill dir: `~/.claude/skills/`, `~/.config/opencode/skills/`, `$HOME/.agents/skills/` for claude-code, opencode, codex respectively):

```yaml
extra_instruction_paths:
  - instructions/apify-skill.md

agents:
  - name: opencode
    model_name: openrouter/deepseek/deepseek-chat-v3.1
    skills:
      - skills/apify-ultimate-scraper   # host path, relative to repo root
```

`extra_instruction_paths` is a job-level field. Each file's contents get appended to the task's `instruction.md` with `\n\n` separators (`src/harbor/models/task/task.py:181`).

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
6. Add `instructions/<vendor>-mcp.md` and/or `instructions/<vendor>-skill.md` snippets.
7. Add a job config under `configs/` declaring `mcp_servers:` and/or `skills:` plus the matching `extra_instruction_paths:` entry.

## Existing tasks

- `tasks/apify-fetch-actor-id/` - real Apify call, not gameable. MCP + skill variants both wired.
- `tasks/apify-scrape-page/` - runs an Actor and reads its dataset. MCP + skill variants both wired.
- `tasks/apify-mcp-connected/` - connection smoke, gameable. MCP-only (no skill equivalent makes sense).
