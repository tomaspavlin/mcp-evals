#!/bin/sh
# Auth + connectivity probe for the gh CLI. gh picks up GITHUB_TOKEN from the
# env automatically — no login step. `gh api user` confirms the token works
# and api.github.com answers. Non-zero exit aborts the trial.
set -e
if ! gh api user >/dev/null 2>&1; then
  echo "CONNECTOR_PROBE_FAILED: github-cli: 'gh api user' failed" >&2
  exit 1
fi
echo "cli-probe[github]: ok"
