"""Project-wide defaults applied when our RunConfig / CLI flags don't override."""

DEFAULT_ENVIRONMENT = {
    "type": "e2b",
    "override_cpus": 1,
    "override_memory_mb": 2048,
    "override_storage_mb": 10240,
}
DEFAULT_N_CONCURRENT_TRIALS = 5
DEFAULT_AGENT_KWARGS = {"max_budget_usd": 1.50, "max_turns": 35}

# Per-agent kwarg overrides, layered on top of DEFAULT_AGENT_KWARGS and below
# any kwargs the user supplied in their RunConfig.
# codex >=0.142.2 defers MCP tools behind a tool_search virtual tool (PR #29486);
# gpt-5.4 via OpenRouter (wire_api=responses) doesn't engage with that flow and
# emits zero tool calls. Pin to the last known-good release.
DEFAULT_AGENT_KWARGS_BY_NAME = {
    "codex": {"version": "0.142.1"},
}
