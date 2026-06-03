# MCP task pattern

How we wire an auth'd remote MCP into a Harbor task. Fork this to add another vendor (Linear, Notion, hosted GitHub).

## The auth blocker

Harbor's `MCPServerConfig` accepts `name | transport | url | command | args`. **No `headers`, no `env`.** Unsupported fields are dropped on purpose. So you cannot declare an `Authorization: Bearer <TOKEN>` remote MCP in `task.toml`. Confirmed against `src/harbor/models/task/config.py` + PR #1675.

## The workaround: stdio wrapper

- Declare a stdio MCP in `task.toml` whose `command` is a wrapper script.
- Wrapper runs `mcp-remote` (npm proxy), which speaks stdio locally and forwards to the remote streamable-http endpoint with an injected `Authorization` header.
- Token reaches the container via `[environment.env]` in `task.toml`, which IS supported by Harbor and forwards from host `os.environ`.

## File layout

```
tasks/<name>/
  task.toml
  instruction.md
  environment/
    Dockerfile               # node:20-bookworm + `npm install -g mcp-remote`
    apify-mcp-proxy.sh       # the wrapper (see template below)
  tests/
    test.sh, test_outputs.py
  solution/solve.sh
```

## task.toml snippet

```toml
[environment.env]
APIFY_TOKEN = "${APIFY_TOKEN}"        # required; errors if unset on host

[[environment.mcp_servers]]
name = "apify"
transport = "stdio"
command = "/usr/local/bin/apify-mcp-proxy"
args = []
```

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

**The expected answer must require an actual MCP tool call**, not a name the agent can guess from the prompt. We tried a "list connected MCP names → /app/mcps.txt" task and the agent passed by writing `apify\n` from the init message alone, with `connected: []`. Use a stable opaque value the API returns (e.g., `moJRLRc85AitArpNN` for `apify/web-scraper`).

## Adapt for another vendor

1. Copy `tasks/apify-fetch-actor-id/` to `tasks/<vendor>-<task>/`.
2. In `apify-mcp-proxy.sh`: change the URL, the env var name, and the redaction regex.
3. In `task.toml`: rename the MCP, swap the env var.
4. In `.env.example` + `.env`: add the new token.
5. Rewrite `instruction.md` and `test_outputs.py` for the new vendor.

## Two existing tasks

- `tasks/apify-fetch-actor-id/` - real MCP tool call, not gameable. ~$0.21/run on haiku.
- `tasks/apify-mcp-connected/` - connection smoke, gameable (kept as a cheap canary).
