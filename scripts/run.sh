#!/bin/bash
# Run a Harbor job config with .env loaded and --job-name set to the config
# basename. On collision (FileExistsError) remove jobs/<name> and rerun. Extra
# args are forwarded to `harbor run`.
#
# Usage: ./scripts/run.sh configs/<name>.yaml [harbor run flags...]
set -eu

if [ $# -lt 1 ]; then
  echo "Usage: $0 configs/<name>.yaml [extra harbor run flags...]" >&2
  exit 2
fi

CONFIG="$1"
shift

if [ ! -f "$CONFIG" ]; then
  echo "Config not found: $CONFIG" >&2
  exit 1
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

JOB_NAME="$(basename "$CONFIG" .yaml)"

yes | harbor run -c "$CONFIG" --job-name "$JOB_NAME" "$@"
