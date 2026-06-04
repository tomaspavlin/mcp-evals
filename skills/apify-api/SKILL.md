---
name: apify-api
description: Call the Apify REST API directly with curl and an APIFY_TOKEN env var.
---

# apify-api

TBD

Use the Apify REST API (https://api.apify.com/v2/) instead of an MCP server.

The token is in the `APIFY_TOKEN` environment variable. Pass it as a Bearer token:

```bash
curl -sS -H "Authorization: Bearer $APIFY_TOKEN" \
  "https://api.apify.com/v2/acts/apify~web-scraper"
```

TODO: flesh this out (common endpoints, pagination, dataset fetch, run polling).
