#!/bin/bash
set -e
# Reference answer for pr_then_checks (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
PR #50863 ('fix: standardize MS Teams to Microsoft Teams across docs') has CI checks from multiple workflows. Most checks passed, with a few failures (e.g. check-docs, channels, check).
EOF
