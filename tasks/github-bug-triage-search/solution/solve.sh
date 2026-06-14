#!/bin/bash
set -e
# Reference answer for bug_triage_search (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The total result count should be large - in the hundreds or thousands, or expressed as 'at least N' where N is well over 100 (the exact figure drifts; do not require a specific number). Reporting a small number like 5 or 30 (which indicates only a default page was counted) is incorrect. The agent must report 5 specific issues with all three requested fields (title, state, assignee).
EOF
