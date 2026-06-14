#!/bin/bash
set -e
# Reference answer for weekly_catchup (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The open issue count should be in the thousands (e.g. ~8700). Reporting just the page size (e.g. 30) as the total count is incorrect. The agent must report 5 specific merged PRs with titles and authors.
EOF
