#!/bin/bash
set -e
# Reference answer for release_then_body (openclaw/openclaw). The trajectory judge
# grades real agents; the oracle is not gradeable here (no trajectory).
cat <<'EOF'
The first 3 items are: 'fix(compaction): use full-session token count for post-compaction sanity check' by efe-arv, 'fix(telegram): thread media transport policy into SSRF' by obviyus, and 'fix: handle Discord gateway metadata fetch failures' by jalehman.
EOF
