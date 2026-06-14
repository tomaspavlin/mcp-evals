#!/bin/bash
set -e
# Reference answer for weekly_catchup (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The open issue count must be a realistic large number in the thousands obtained from a real query (the exact figure drifts; do not require a specific number). Reporting just the default page size (e.g. 30 or 100) as the total count is incorrect. The agent must also report 5 specific merged PRs with titles and authors.
EOF
