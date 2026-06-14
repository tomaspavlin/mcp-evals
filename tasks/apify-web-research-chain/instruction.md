Your task: use Apify to research **Crawlee** (the open-source web scraping library) by chaining two steps.

1. Use a web **search** Apify Actor to find the official Crawlee website (do not hardcode a URL you already know — obtain it from the search results).
2. Use a website **crawler/content** Apify Actor to crawl that official website, and from the crawled content report:
   - A one-sentence description of what Crawlee is, as stated on the site.
   - Which programming language(s) Crawlee supports.

Write your answer to `/app/answer.md` as plain text.

Use Apify Actors for both steps. Do not answer from prior knowledge, and do not use any built-in web-fetch/browse tool or `curl` — the URL must come from a search Actor run and the page content must come from a crawler Actor run.
