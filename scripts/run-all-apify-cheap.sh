#!/bin/bash
# Run the four apify-all-opencode-cheap variant configs sequentially.
# Continues past failures so one bad variant doesn't block the rest.
#
# Usage: ./scripts/run-all-apify-cheap.sh [extra connector-evals flags...]
set -u

FAILED=()

for variant in mcp cli mcpc skill; do
  CONFIG="configs/apify-all-opencode-cheap-${variant}-eval.yaml"
  echo "=== $CONFIG ==="
  if ! uv run connector-evals run -c "$CONFIG" -y "$@"; then
    FAILED+=("$CONFIG")
  fi
done

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "FAILED: ${FAILED[*]}" >&2
  exit 1
fi
