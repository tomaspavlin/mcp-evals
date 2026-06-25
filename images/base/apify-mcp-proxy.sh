#!/bin/bash
# Stdio shim for https://mcp.apify.com/. Harbor's MCPServerConfig has no
# `headers` field, so we can't declare an auth'd remote MCP directly - we
# declare stdio + this wrapper instead.
#
# Token resolution: prefer $APIFY_TOKEN (back-compat / ad-hoc debugging);
# else read /etc/apify-mcp.token (written by apps/apify/mcp/setup.sh, kept
# out of the agent's env so the agent can't `echo $APIFY_TOKEN` it into the
# trajectory). chmod 400 root-only — the agent runs as root so this is
# cosmetic, but matches the cli/skill/mcpc cells' posture.
#
# stderr is redacted (strip apify_api_* tokens) and tee'd to
# /logs/agent/apify-mcp-proxy.stderr so we have a record of mcp-remote's
# handshake output when opencode/codex/claude-code swallow it. tee failure
# (missing dir, perms) is suppressed so it never breaks the stderr pipe.
set -eu
TOKEN_FILE=/etc/apify-mcp.token
if [ -z "${APIFY_TOKEN:-}" ] && [ -r "$TOKEN_FILE" ]; then
  APIFY_TOKEN=$(cat "$TOKEN_FILE")
fi
: "${APIFY_TOKEN:?APIFY_TOKEN env var or $TOKEN_FILE required}"
LOG=/logs/agent/apify-mcp-proxy.stderr
mcp-remote https://mcp.apify.com/ --header "Authorization: Bearer $APIFY_TOKEN" \
  2> >(sed -E "s/apify_api_[A-Za-z0-9]+/apify_api_REDACTED/g" \
       | tee -a "$LOG" 2>/dev/null >&2)
