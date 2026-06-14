#!/bin/bash
set -e
# Reference answer for pr_review_prep (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
PR #50782 is titled 'Gateway: harden OpenResponses file-context escaping', authored by joshavant. The agent should report CI check pass/fail counts and summarize any comments.
EOF
