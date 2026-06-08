#!/bin/bash
# Stdio shim for https://api.githubcopilot.com/mcp/. Harbor's MCPServerConfig has
# no `headers` field, so we can't declare an auth'd remote MCP directly - we
# declare stdio + this wrapper instead.
set -eu
: "${GITHUB_TOKEN:?GITHUB_TOKEN env var is required}"
mcp-remote https://api.githubcopilot.com/mcp/ --header "Authorization: Bearer $GITHUB_TOKEN" \
  2> >(sed -E "s/(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]+/\1REDACTED/g" >&2)
