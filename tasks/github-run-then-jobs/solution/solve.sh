#!/bin/bash
set -e
# Reference answer for run_then_jobs (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The agent must identify a specific run ID and report individual job names with their statuses (success/failure/skipped), not just an overall run status.
EOF
