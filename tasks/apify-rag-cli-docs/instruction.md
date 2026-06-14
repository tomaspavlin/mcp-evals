Your task: build a focused dataset of the Apify CLI documentation.

1. Use the Apify Actor `apify/website-content-crawler` to crawl `https://docs.apify.com/cli/`.
   - Set crawl depth to **2** (`maxCrawlDepth`).
   - Cap pages at **50** or fewer (`maxCrawlPages`) — this is a cost guardrail.
2. From the resulting dataset items, compute:
   - `pageCount`: the total number of pages the crawl returned.
   - `installPreview`: the **first 200 characters** of the `markdown` field of the page that documents installation/setup of the Apify CLI (typically the page whose URL path contains the word `install`).
   - `urlsContainingActor`: the number of crawled URLs whose path contains the substring `actor` (case-insensitive).
3. Write the result to `/app/cli_rag.json` as a JSON object with exactly these three keys, e.g.:

```json
{
  "pageCount": 23,
  "installPreview": "# Installation\n\nThe Apify CLI is available...",
  "urlsContainingActor": 8
}
```

Base your answers strictly on what the Actor returns.
