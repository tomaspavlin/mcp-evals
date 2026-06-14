#!/bin/bash
set -e
# Reference answer for merged_pr_ci_audit (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The agent must report exactly 10 PRs with per-PR CI status (not just an overall summary). The final count of fully-green PRs must be based on actual check data, not assumed.
EOF
