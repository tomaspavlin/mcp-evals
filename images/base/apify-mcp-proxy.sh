#!/bin/bash
# Stdio shim for https://mcp.apify.com/. Harbor's MCPServerConfig has no
# `headers` field, so we can't declare an auth'd remote MCP directly - we
# declare stdio + this wrapper instead.
#
# stderr is redacted (strip apify_api_* tokens) and tee'd to
# /logs/agent/apify-mcp-proxy.stderr so we have a record of mcp-remote's
# handshake output when opencode/codex/claude-code swallow it. tee failure
# (missing dir, perms) is suppressed so it never breaks the stderr pipe.
set -eu
: "${APIFY_TOKEN:?APIFY_TOKEN env var is required}"
LOG=/logs/agent/apify-mcp-proxy.stderr
mcp-remote https://mcp.apify.com/ --header "Authorization: Bearer $APIFY_TOKEN" \
  2> >(sed -E "s/apify_api_[A-Za-z0-9]+/apify_api_REDACTED/g" \
       | tee -a "$LOG" 2>/dev/null >&2)
