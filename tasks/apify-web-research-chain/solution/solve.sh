#!/bin/bash
set -e
# Oracle reference answer. Note: this writes the result directly and does NOT
# run search/crawler Actors, so the trajectory-based judge criteria
# (obtained_url_via_search_actor, crawled_site_via_actor, chained_two_actors)
# are NOT expected to pass for the oracle. They grade real agents that must
# actually chain the two Actors; the oracle validates the result path only.
cat > /app/answer.md <<'EOF'
Crawlee (https://crawlee.dev)

- Description: Crawlee is a web scraping and browser automation library for building reliable crawlers.
- Supported languages: JavaScript / TypeScript (Node.js) and Python.
EOF
