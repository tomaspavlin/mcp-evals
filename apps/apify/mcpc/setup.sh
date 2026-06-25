#!/bin/sh
# Open the @apify mcpc session before the agent runs. Matches the cli/skill
# cells (login at setup); the bridge daemon and session stay live for the
# agent. See images/base/mcpc-probe.sh for the probe contract.
set -e
exec mcpc-probe --name apify --session @apify \
  --url https://mcp.apify.com --auth "Bearer $APIFY_TOKEN"
