Your task chains Apify and GitHub:

1. Search the Apify Store for Actors with the keyword `instagram scraper`. Among the results, find the one published by user `apify` with slug `apify/instagram-scraper`. Report its `id` field (the opaque ID string returned by the API).
2. Look up two GitHub repositories: `apify/crawlee` and `apify/crawlee-python`. From each, extract:
   - `default_branch`
   - `license.spdx_id`
   - The length of the `topics` array (an integer count).
3. Determine which of the two repositories has more topics. If they have the same number of topics, report `"tied"`. Otherwise report the repo name without the owner prefix (`"crawlee"` or `"crawlee-python"`).
4. Write a JSON file to `/app/result.json` with exactly these six keys:
   ```json
   {
     "actor_id": "<id from step 1>",
     "crawlee_default_branch": "<default_branch of apify/crawlee>",
     "crawlee_license": "<license.spdx_id of apify/crawlee>",
     "crawlee_python_default_branch": "<default_branch of apify/crawlee-python>",
     "crawlee_python_license": "<license.spdx_id of apify/crawlee-python>",
     "more_topics_repo": "<crawlee | crawlee-python | tied>"
   }
   ```

Write the values exactly as returned by the API, with no extra whitespace or formatting.
