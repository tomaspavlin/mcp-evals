#!/bin/bash
# Run all four apify-all variant configs (mcp, cli, mcpc, skill) sequentially.
# Continues past failures so one bad variant doesn't block the rest.
#
# Usage: ./scripts/run-all-apify.sh [extra mcp-evals flags...]
set -u

FAILED=()

for variant in mcp cli mcpc skill; do
  CONFIG="configs/apify-all-${variant}-eval.yaml"
  echo "=== $CONFIG ==="
  if ! uv run mcp-evals run -c "$CONFIG" -y "$@"; then
    FAILED+=("$CONFIG")
  fi
done

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "FAILED: ${FAILED[*]}" >&2
  exit 1
fi
