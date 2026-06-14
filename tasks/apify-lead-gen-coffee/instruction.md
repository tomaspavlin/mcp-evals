Your task: you are sourcing potential partners for a specialty coffee distribution business.

Use Apify to research specialty coffee roasters in **Portland, Oregon, USA**:

1. Use a Google Maps Apify Actor to find places matching the search "specialty coffee roaster" in Portland, OR. Restrict results to places with a rating of at least 4.5 and at least 100 reviews.
2. Pick the **top 3 places by total number of reviews** (most-reviewed first).
3. For each, follow up by using a website-content / RAG-web Apify Actor to fetch that place's website (the website URL Google Maps reports for the place). If the website page contains a contact email, capture it.

Write a JSON array of exactly **3 entries** to `/app/leads.json`. Each entry must have the keys:

- `name`: place name (string)
- `address`: full street address as Google Maps reports it (string)
- `website`: website URL the Maps Actor reports for the place (string; empty string if Maps does not list one)
- `email`: the first contact email visible on the website (string; empty string if none found)

Base your answers strictly on data the Actors return. Do not fabricate emails — if no email is visible on the site, leave the field as an empty string.
