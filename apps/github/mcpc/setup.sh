#!/bin/sh
# See apps/apify/mcpc/setup.sh for the rationale.
set -e
SESSION='@github'
RETRIES=2

count_tools() {
  python3 -c 'import sys,json
try: d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)
except Exception: print(0)'
}

attempt() {
  mcpc connect https://api.githubcopilot.com/mcp/ "$SESSION" \
    --header "Authorization: Bearer $GITHUB_TOKEN" >/dev/null 2>&1 || return 1
  n=$(mcpc --json "$SESSION" tools-list 2>/dev/null | count_tools)
  [ "${n:-0}" -ge 1 ] && echo "$n"
}

i=0
while [ "$i" -le "$RETRIES" ]; do
  i=$((i + 1))
  if n=$(attempt); then
    echo "mcpc-probe[github]: ok, $n tools (attempt $i), $SESSION left open for agent"
    exit 0
  fi
  mcpc close "$SESSION" >/dev/null 2>&1 || true
  echo "mcpc-probe[github]: attempt $i failed" >&2
  sleep 1
done
echo "CONNECTOR_PROBE_FAILED: github-mcpc: connect or tools-list failed after $i attempts" >&2
exit 1
