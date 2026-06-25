#!/bin/sh
# See apps/apify/mcpc/setup.sh.
set -e
exec mcpc-probe --name github --session @github \
  --url https://api.githubcopilot.com/mcp/ --auth "Bearer $GITHUB_TOKEN"
