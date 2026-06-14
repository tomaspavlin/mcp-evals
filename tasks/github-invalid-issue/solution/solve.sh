#!/bin/bash
set -e
# Reference answer for invalid_issue (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
Issue #999999 does not exist - the agent should report a not-found error.
EOF
