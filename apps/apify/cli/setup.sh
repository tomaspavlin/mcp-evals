#!/bin/sh
# Auth + connectivity probe for the apify CLI. `apify login` persists creds
# to ~/.apify/auth.json; `apify info` confirms the v2 API answers. Non-zero
# exit aborts the trial before any agent tokens are billed.
set -e
apify login --token "$APIFY_TOKEN"
if ! apify info >/dev/null 2>&1; then
  echo "CONNECTOR_PROBE_FAILED: apify-cli: 'apify info' failed after login" >&2
  exit 1
fi
echo "cli-probe[apify]: ok"
