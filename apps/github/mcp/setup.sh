#!/bin/sh
# See apps/apify/mcp/setup.sh for the rationale.
set -e
exec mcp-stdio-probe --name github --timeout 25 --retries 2 -- /usr/local/bin/github-mcp-proxy
