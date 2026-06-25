The `mcpc` CLI is installed and already connected to GitHub as `@github`. Use it for GitHub operations in the task above.

```
mcpc @github tools-list
mcpc @github tools-get <tool-name>
mcpc --json @github tools-call <tool-name> arg:=value
mcpc --help
```

Do NOT use the `gh` CLI, the GitHub MCP server directly, or `curl`/direct GitHub API calls. If `mcpc` cannot accomplish the task, stop and say so rather than escaping to other tools.
