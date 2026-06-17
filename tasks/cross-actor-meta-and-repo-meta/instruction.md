Your task uses both Apify and GitHub:

1. Look up the Apify Actor `apify/instagram-scraper`. From the API response, extract:
   - `id` (the opaque ID string)
   - `title`
   - `name` (the slug name, without the username prefix)
2. Look up the GitHub repository `apify/crawlee-python`. From the API response, extract:
   - `default_branch`
   - `license.spdx_id`
3. Write a JSON file to `/app/result.json` with exactly these five keys:
   ```json
   {
     "actor_id": "<id from step 1>",
     "actor_title": "<title from step 1>",
     "actor_name": "<name from step 1>",
     "repo_default_branch": "<default_branch from step 2>",
     "repo_license": "<license.spdx_id from step 2>"
   }
   ```

Write the values exactly as returned by the API, with no extra whitespace or formatting.
