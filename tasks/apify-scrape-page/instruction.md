An Apify MCP server is configured and available to you. It exposes tools for searching Actors, fetching Actor details, calling Actors, and reading docs.

Your task:

1. Use the Apify MCP to run the Actor `apify/rag-web-browser` against the URL `https://example.com` and retrieve its scraped output.
2. From the resulting dataset item, extract the page title (the `metadata.title` field).
3. Write that title to `/app/result.txt`.

Write the title exactly as returned by the tool, with no quotes, whitespace, or extra formatting.
