The `mcpc` CLI is installed and already connected to Apify as `@apify`. Use it for Apify operations in the task above.

```
mcpc @apify tools-list
mcpc @apify tools-get <tool-name>
mcpc --json @apify tools-call <tool-name> arg:=value
mcpc --help
```

Do NOT use the `apify` CLI, the Apify MCP server directly, or direct `https://api.apify.com` calls. If `mcpc` cannot accomplish the task, stop and say so rather than escaping to other tools.
