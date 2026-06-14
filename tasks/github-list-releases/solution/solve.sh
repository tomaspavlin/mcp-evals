#!/bin/bash
set -e
# Reference answer for list_releases (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The 3 most recent tags are v2026.3.13-1, v2026.3.13-beta.1, and v2026.3.12.
EOF
