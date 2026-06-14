#!/bin/bash
set -e
# Reference answer for issue_then_comments (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The agent must report on the single most recent bug-labeled issue. If that issue has no comments, reporting 'no comments' is correct. Searching through multiple issues to find one with comments is incorrect - the task asks about the most recent one specifically.
EOF
