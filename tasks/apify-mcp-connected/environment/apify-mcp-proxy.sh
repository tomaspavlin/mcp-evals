#!/bin/bash
# stdio MCP wrapper: proxies to the remote Apify MCP, injecting auth from $APIFY_TOKEN.
# APIFY_TOKEN is forwarded into the container via [environment.env] in task.toml.
# stderr is piped through sed to redact the token, because mcp-remote logs the raw
# Authorization header on startup and that stream is captured by the agent's logger.
set -eu
: "${APIFY_TOKEN:?APIFY_TOKEN env var is required}"
mcp-remote https://mcp.apify.com/ --header "Authorization: Bearer $APIFY_TOKEN" \
  2> >(sed -E "s/apify_api_[A-Za-z0-9]+/apify_api_REDACTED/g" >&2)
