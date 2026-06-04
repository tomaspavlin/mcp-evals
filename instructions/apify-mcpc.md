The `mcpc` CLI is installed and the `APIFY_TOKEN` env var is set. Use it to complete the task above.

Open a session once, then call tools through it:

```
mcpc connect https://mcp.apify.com @apify --header "Authorization: Bearer $APIFY_TOKEN"
mcpc @apify tools-list
mcpc @apify tools-get <tool-name>
mcpc --json @apify tools-call <tool-name> arg:=value
mcpc --help
```
