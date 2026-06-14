#!/bin/bash
set -e
# Reference answer for nonexistent_repo (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The repository openclaw/this-does-not-exist does not exist - the agent should report an error.
EOF
