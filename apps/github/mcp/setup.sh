#!/bin/sh
# See apps/apify/mcp/setup.sh for the rationale.
set -e
TOKEN_FILE=/etc/github-mcp.token
printf '%s' "$GITHUB_TOKEN" > "$TOKEN_FILE"
chmod 400 "$TOKEN_FILE"
unset GITHUB_TOKEN
exec mcp-stdio-probe --name github --timeout 25 --retries 2 -- /usr/local/bin/github-mcp-proxy
