You have access to Apify (via MCP, a skill, or another tool variant depending on the run). Use whatever Apify access is available to you to run Actors and retrieve their output.

Your task:

1. Run the Actor `apify/rag-web-browser` against the URL `https://example.com` and retrieve its scraped output.
2. From the resulting dataset item, extract the page title (the `metadata.title` field).
3. Write that title to `/app/result.txt`.

Write the title exactly as returned by the API, with no quotes, whitespace, or extra formatting.
