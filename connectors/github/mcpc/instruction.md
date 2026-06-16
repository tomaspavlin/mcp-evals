The `mcpc` CLI is installed and the `GITHUB_TOKEN` env var is set. Use it for GitHub operations in the task above.

Open a session once, then call tools through it:

```
mcpc connect https://api.githubcopilot.com/mcp @github --header "Authorization: Bearer $GITHUB_TOKEN"
mcpc @github tools-list
mcpc @github tools-get <tool-name>
mcpc --json @github tools-call <tool-name> arg:=value
mcpc --help
```
