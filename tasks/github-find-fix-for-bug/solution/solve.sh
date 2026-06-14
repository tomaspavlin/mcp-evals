#!/bin/bash
set -e
# Reference answer for find_fix_for_bug (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The agent must identify a specific issue number and title, then actually search for PRs referencing it (not just guess). The conclusion about whether a fix is in progress must be based on search results, not assumption.
EOF
