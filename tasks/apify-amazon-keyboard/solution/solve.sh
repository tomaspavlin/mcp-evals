#!/bin/bash
set -e
# Oracle reference answer. Writes a plausible artifact directly without running
# Apify Actors — trajectory-based judge criteria (ran_amazon_apify_actor,
# queried_for_mechanical_keyboard) are NOT expected to pass for the oracle.
# The ASIN and brand here are placeholders representing a typical winner from
# the under-$100 wired-mechanical bracket; values may drift over time and are
# verified via set-membership / range checks, not exact equality.
cat > /app/keyboard.json <<'EOF'
{
  "asin": "B07GBZ4Q68",
  "brand": "Redragon",
  "price": 39.99,
  "rating": 4.5,
  "reviewCount": 78000
}
EOF
