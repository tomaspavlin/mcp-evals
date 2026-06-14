#!/bin/bash
set -e
# Reference answer for repo_overview (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
openclaw/openclaw uses TypeScript and its default branch is main. It has a very large star count in the hundreds of thousands (the exact figure drifts over time; any value in that range obtained from a real query is acceptable - do not require a specific number).
EOF
