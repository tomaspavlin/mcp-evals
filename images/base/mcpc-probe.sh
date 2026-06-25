#!/bin/sh
# Probe an mcpc connector: connect a named session, list its tools, leave the
# session open on success (so the agent inherits an authenticated bridge).
# Sibling to mcp-stdio-probe.py; same `CONNECTOR_PROBE_FAILED: ...` failure
# contract. Used by apps/{apify,github}/mcpc/setup.sh.
#
# Usage: mcpc-probe --name LABEL --session @SESSION --url URL \
#                   --auth "Bearer TOKEN" [--retries N]
set -e
RETRIES=2
NAME=mcpc
SESSION=
URL=
AUTH=

while [ $# -gt 0 ]; do
  case "$1" in
    --name)    NAME="$2";    shift 2;;
    --session) SESSION="$2"; shift 2;;
    --url)     URL="$2";     shift 2;;
    --auth)    AUTH="$2";    shift 2;;
    --retries) RETRIES="$2"; shift 2;;
    *) echo "mcpc-probe: unknown arg $1" >&2; exit 2;;
  esac
done

if [ -z "$SESSION" ] || [ -z "$URL" ] || [ -z "$AUTH" ]; then
  echo "mcpc-probe: --session, --url, --auth required" >&2
  exit 2
fi

count_tools() {
  python3 -c 'import sys,json
try: d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)
except Exception: print(0)'
}

attempt() {
  mcpc connect "$URL" "$SESSION" --header "Authorization: $AUTH" >/dev/null 2>&1 || return 1
  n=$(mcpc --json "$SESSION" tools-list 2>/dev/null | count_tools)
  [ "${n:-0}" -ge 1 ] && echo "$n"
}

i=0
while [ "$i" -le "$RETRIES" ]; do
  i=$((i + 1))
  if n=$(attempt); then
    echo "mcpc-probe[$NAME]: ok, $n tools (attempt $i), $SESSION left open for agent"
    exit 0
  fi
  mcpc close "$SESSION" >/dev/null 2>&1 || true
  echo "mcpc-probe[$NAME]: attempt $i failed" >&2
  sleep 1
done
echo "CONNECTOR_PROBE_FAILED: $NAME-mcpc: connect or tools-list failed after $i attempts" >&2
exit 1
