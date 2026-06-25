"""Project-wide defaults applied when our RunConfig / CLI flags don't override."""

DEFAULT_ENVIRONMENT = {
    "type": "e2b",
    "override_cpus": 1,
    "override_memory_mb": 2048,
    "override_storage_mb": 10240,
}
DEFAULT_N_CONCURRENT_TRIALS = 5
DEFAULT_AGENT_KWARGS = {"max_budget_usd": 1.50, "max_turns": 35}
