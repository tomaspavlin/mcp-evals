Your task:

1. Run the Apify Actor `apify/rag-web-browser` against the URL `https://example.com` and retrieve its scraped output.
2. From the resulting dataset item, find the page's URL — the `metadata.url` field as returned by the Actor.
3. Extract only the **hostname** from that URL (no scheme, no path, no trailing slash; e.g. for `https://docs.example.com/foo` the hostname is `docs.example.com`).

Write the hostname to `/app/host.txt`, with no quotes or extra whitespace.
