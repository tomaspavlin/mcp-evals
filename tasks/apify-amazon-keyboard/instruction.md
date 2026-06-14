Your task: a customer wants a budget mechanical keyboard recommendation. Use Apify to identify the **most-reviewed wired mechanical keyboard** for sale on **amazon.com** that meets ALL of these criteria:

- listed price below **$100 USD**
- average customer rating **≥ 4.4**
- **wired** (not wireless)
- at least **1,000 customer reviews**

Among products meeting every criterion, pick the one with the **highest review count**.

Write its details to `/app/keyboard.json` as a JSON object with these keys:

- `asin`: Amazon Standard Identification Number (string; format `B0[A-Z0-9]{8}`)
- `brand`: brand name (string; lowercase or original case is fine)
- `price`: numeric price in USD (number, no currency symbol)
- `rating`: average star rating to one decimal place (number)
- `reviewCount`: integer review count (integer)

Base your answer on live data returned by Apify, not on prior knowledge.
