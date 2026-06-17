Your task uses both Apify and GitHub:

1. Look up the Apify Actor `apify/instagram-scraper`. Get its `username` field (the owner username as returned by the API).
2. Look up the GitHub repository `apify/apify-sdk-python`. Get its `language` field (the primary language as returned by the API).
3. Write a JSON file to `/app/result.json` with exactly these two keys:
   ```json
   {"actor_username": "<username from step 1>", "repo_language": "<language from step 2>"}
   ```

Write the values exactly as returned by the API, with no extra whitespace or formatting.
