#!/bin/bash
set -e
# Oracle reference answer. Note: this writes the result directly and does NOT
# run a Google Maps Actor, so the trajectory-based judge criteria
# (ran_google_maps_actor, actor_query_targets_louvre) are NOT expected to pass
# for the oracle — they exist to grade real agents that must actually run the
# Actor. The oracle validates the result-grading path only.
cat > /app/answer.md <<'EOF'
Louvre Museum, Paris

- Address: Rue de Rivoli, 75001 Paris, France
- Category: Art museum
EOF
