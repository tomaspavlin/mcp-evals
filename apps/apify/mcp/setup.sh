#!/bin/sh
# Stash the token to a root-only file the proxy reads (kept out of the
# agent's env so the agent can't `echo $APIFY_TOKEN` it into the trajectory;
# matches the cli/skill/mcpc cells). Then probe the apify MCP stdio proxy
# before the agent runs - if mcp.apify.com is rate-limiting or mcp-remote's
# handshake stalls, opencode silently drops the server and the agent sees
# zero MCP tools (Cat 4 in docs/off-channel-call-analysis.md). The probe
# reproduces exactly what the harness does on spawn, so a green probe ~=
# the agent will see tools. Non-zero exit aborts the trial.
set -e
TOKEN_FILE=/etc/apify-mcp.token
printf '%s' "$APIFY_TOKEN" > "$TOKEN_FILE"
chmod 400 "$TOKEN_FILE"
unset APIFY_TOKEN
exec mcp-stdio-probe --name apify --timeout 25 --retries 2 -- /usr/local/bin/apify-mcp-proxy
