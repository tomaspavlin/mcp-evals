#!/bin/sh
# See apps/apify/cli/setup.sh — the skill cell uses the same CLI underneath.
set -e
apify login --token "$APIFY_TOKEN"
if ! apify info >/dev/null 2>&1; then
  echo "CONNECTOR_PROBE_FAILED: apify-skill: 'apify info' failed after login" >&2
  exit 1
fi
echo "cli-probe[apify-skill]: ok"
