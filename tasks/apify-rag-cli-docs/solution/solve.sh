#!/bin/bash
set -e
# Oracle reference answer. Writes a plausible artifact directly without running
# the Actor — trajectory-based judge criteria (ran_website_content_crawler,
# respected_page_cap) are NOT expected to pass for the oracle. Counts and
# preview text reflect a typical successful crawl of docs.apify.com/cli/.
cat > /app/cli_rag.json <<'EOF'
{
  "pageCount": 18,
  "installPreview": "# Installation\n\nThe Apify CLI is available as the `apify-cli` package on npm. To install it globally, run:\n\n```bash\nnpm install -g apify-cli\n```\n\nAlternatively, you",
  "urlsContainingActor": 6
}
EOF
