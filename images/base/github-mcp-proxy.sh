#!/bin/bash
# Stdio shim for https://api.githubcopilot.com/mcp/. Harbor's MCPServerConfig has
# no `headers` field, so we can't declare an auth'd remote MCP directly - we
# declare stdio + this wrapper instead.
#
# Token resolution: prefer $GITHUB_TOKEN (back-compat / ad-hoc debugging);
# else read /etc/github-mcp.token (written by apps/github/mcp/setup.sh, kept
# out of the agent's env). See apps/apify/mcp/setup.sh comments for rationale.
#
# stderr is redacted (strip gh tokens) and tee'd to
# /logs/agent/github-mcp-proxy.stderr so we have a record of mcp-remote's
# handshake output when opencode/codex/claude-code swallow it. tee failure
# (missing dir, perms) is suppressed so it never breaks the stderr pipe.
set -eu
TOKEN_FILE=/etc/github-mcp.token
if [ -z "${GITHUB_TOKEN:-}" ] && [ -r "$TOKEN_FILE" ]; then
  GITHUB_TOKEN=$(cat "$TOKEN_FILE")
fi
: "${GITHUB_TOKEN:?GITHUB_TOKEN env var or $TOKEN_FILE required}"
LOG=/logs/agent/github-mcp-proxy.stderr
mcp-remote https://api.githubcopilot.com/mcp/ --header "Authorization: Bearer $GITHUB_TOKEN" \
  2> >(sed -E "s/(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+/\1REDACTED/g" \
       | tee -a "$LOG" 2>/dev/null >&2)
