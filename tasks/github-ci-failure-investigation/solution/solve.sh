#!/bin/bash
set -e
# Reference answer for ci_failure_investigation (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The agent must report 5 distinct failed runs with run IDs, workflow names, and specific failed job names. Reporting fewer than 5 or omitting job-level detail is incomplete.
EOF
