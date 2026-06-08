"""Project-wide defaults applied when our RunConfig / CLI flags don't override."""

DEFAULT_ENVIRONMENT = {"type": "docker"}
DEFAULT_N_CONCURRENT_TRIALS = 1
DEFAULT_AGENT_KWARGS = {"max_budget_usd": 1.50, "max_turns": 20}
