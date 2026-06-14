#!/bin/bash
set -e
# Reference answer for list_labels (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
openclaw/openclaw has many labels - well over 100, and the count grows over time. The agent must paginate through all label pages and report a total in the hundreds (the exact number drifts; any correctly-paginated count of roughly 100-400 is acceptable). Reporting only a single default page (e.g. 30 or 100) as the total is incorrect.
EOF
