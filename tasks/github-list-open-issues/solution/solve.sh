#!/bin/bash
set -e
# Reference answer for list_open_issues (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The agent must run a command to fetch issues and report a specific issue title. Hallucinating a title without running a command is a failure.
EOF
