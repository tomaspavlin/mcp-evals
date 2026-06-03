The goal of this project is to evaluate MCP servers.

The project will be used for:
- MCP servers development
- evaluating existing MCP servers vs their CLI, API or skills alternatives.

We want to do the evaluations on different LLMs and agent harnesses. We want to start with:
- claude code, codex, opencode

It will be built on Harbor framework:
- Harbor docs: https://www.harborframework.com/docs
- Harbor gh: https://github.com/harbor-framework/harbor
- they are creators of https://www.tbench.ai/ - it is built on harbor too

We will define test-cases for mcps as:
- apify: https://mcp.apify.com/
- github
- linear
- notion
We want to start with read-only tools calls for simplicity first.

We want to evaluate:
- task success rate
- token / cost efficiency
- anything else that can be useful
- we ideally also want to output some trace for debugging

If possible, use existing logic of Harbor instead of implementing your own.
