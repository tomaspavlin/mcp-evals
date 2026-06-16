Your task uses both Apify and GitHub:

1. Look up the Apify Actor `apify/web-scraper`. Get its opaque `id` field (the 16-char-ish string returned by the API, not the slug).
2. Look up the GitHub repository `apify/crawlee`. Get its SPDX license id (the `license.spdx_id` field, e.g. `Apache-2.0`).
3. Write a JSON file to `/app/result.json` with exactly these two keys:
   ```json
   {"actor_id": "<id from step 1>", "repo_license": "<spdx_id from step 2>"}
   ```

Write the values exactly as returned by the API, with no extra whitespace or formatting.
