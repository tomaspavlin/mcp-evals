The `mcpc` CLI is installed and the `GITHUB_TOKEN` env var is set. Use it for GitHub operations in the task above.

Open a session once, then call tools through it:

```
mcpc connect https://api.githubcopilot.com/mcp @github --header "Authorization: Bearer $GITHUB_TOKEN"
mcpc @github tools-list
mcpc @github tools-get <tool-name>
mcpc --json @github tools-call <tool-name> arg:=value
mcpc --help
```

Do NOT use the `gh` CLI, the GitHub MCP server directly, or `curl`/direct GitHub API calls. If `mcpc` cannot accomplish the task, stop and say so rather than escaping to other tools.
