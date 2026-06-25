#!/bin/sh
# Open the @apify mcpc session before the agent runs. Matches the cli/skill
# cells, where `apify login` happens at setup so the agent starts already
# authenticated — same fairness across connectors. The probe also catches
# session-creation rate limits on mcp.apify.com (see Cat 2 in
# docs/off-channel-call-analysis.md) and aborts the trial before any tokens
# are billed. On success the bridge daemon and `@apify` session stay live
# for the agent to use; on failure the session is torn down before retry.
set -e
SESSION='@apify'
RETRIES=2

count_tools() {
  python3 -c 'import sys,json
try: d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)
except Exception: print(0)'
}

attempt() {
  mcpc connect https://mcp.apify.com "$SESSION" \
    --header "Authorization: Bearer $APIFY_TOKEN" >/dev/null 2>&1 || return 1
  n=$(mcpc --json "$SESSION" tools-list 2>/dev/null | count_tools)
  [ "${n:-0}" -ge 1 ] && echo "$n"
}

i=0
while [ "$i" -le "$RETRIES" ]; do
  i=$((i + 1))
  if n=$(attempt); then
    echo "mcpc-probe[apify]: ok, $n tools (attempt $i), $SESSION left open for agent"
    exit 0
  fi
  mcpc close "$SESSION" >/dev/null 2>&1 || true
  echo "mcpc-probe[apify]: attempt $i failed" >&2
  sleep 1
done
echo "CONNECTOR_PROBE_FAILED: apify-mcpc: connect or tools-list failed after $i attempts" >&2
exit 1
