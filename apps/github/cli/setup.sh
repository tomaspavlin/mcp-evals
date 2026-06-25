#!/bin/sh
# Auth + connectivity probe for the gh CLI. `gh auth login --with-token`
# persists creds to ~/.config/gh/hosts.yml; the unset before login is
# required because gh refuses to login-with-token while $GITHUB_TOKEN is set
# ("first clear the value from the environment"). After unset gh reads the
# persisted creds for `gh api user` and the agent's calls. Non-zero exit
# aborts the trial.
set -e
TOKEN="$GITHUB_TOKEN"
unset GITHUB_TOKEN
printf '%s\n' "$TOKEN" | gh auth login --with-token
if ! gh api user >/dev/null 2>&1; then
  echo "CONNECTOR_PROBE_FAILED: github-cli: 'gh api user' failed after login" >&2
  exit 1
fi
echo "cli-probe[github]: ok"
