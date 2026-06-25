#!/bin/sh
# Probe the apify MCP stdio proxy before the agent runs. If mcp.apify.com is
# rate-limiting or mcp-remote's handshake stalls, opencode silently drops the
# server and the agent sees zero MCP tools (Cat 4 in
# docs/off-channel-call-analysis.md). The probe reproduces exactly what the
# harness does on spawn, so a green probe ~= the agent will see tools.
# Non-zero exit aborts the trial before any agent tokens are billed.
set -e
exec mcp-stdio-probe --name apify --timeout 25 --retries 2 -- /usr/local/bin/apify-mcp-proxy
