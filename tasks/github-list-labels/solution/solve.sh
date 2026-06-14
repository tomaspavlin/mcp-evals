#!/bin/bash
set -e
# Reference answer for list_labels (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
openclaw/openclaw has approximately 124 labels.
EOF
