#!/bin/bash
set -e
# Oracle reference answer. Writes a plausible artifact directly without running
# Apify Actors, so the trajectory-based judge criteria (ran_google_maps_actor,
# ran_separate_website_actor) are NOT expected to pass for the oracle — they
# exist to grade real agents that must actually run the Actors.
cat > /app/leads.json <<'EOF'
[
  {
    "name": "Stumptown Coffee Roasters",
    "address": "100 SE Salmon St, Portland, OR 97214, USA",
    "website": "https://www.stumptowncoffee.com/",
    "email": ""
  },
  {
    "name": "Heart Coffee Roasters",
    "address": "2211 E Burnside St, Portland, OR 97214, USA",
    "website": "https://www.heartroasters.com/",
    "email": ""
  },
  {
    "name": "Coava Coffee Roasters",
    "address": "1300 SE Grand Ave, Portland, OR 97214, USA",
    "website": "https://coavacoffee.com/",
    "email": ""
  }
]
EOF
