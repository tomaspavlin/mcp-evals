from harbor.models.job.config import JobConfig
from harbor.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    VerifierConfig,
)

from mcp_evals.config import RunConfig
from mcp_evals.defaults import (
    DEFAULT_AGENT_KWARGS,
    DEFAULT_ENVIRONMENT,
    DEFAULT_N_CONCURRENT_TRIALS,
)
from mcp_evals.integrations.model import Integration


def build_job_config(run: RunConfig, integration: Integration) -> JobConfig:
    """Expand RunConfig + Integration + defaults.py into a harbor JobConfig.

    Precedence: per-agent kwargs > DEFAULT_AGENT_KWARGS for agent kwargs;
    RunConfig fields > defaults for everything else. Integration owns
    mcp_servers / skills / instruction append / EVAL_VARIANT.
    """
    if integration.name != run.integration:
        raise ValueError(
            f"Integration mismatch: run requested '{run.integration}', "
            f"loaded '{integration.name}'"
        )

    agents = [
        AgentConfig(
            name=a.name,
            model_name=a.model_name,
            kwargs={**DEFAULT_AGENT_KWARGS, **(a.kwargs or {})},
            mcp_servers=integration.mcp_servers,
            skills=integration.skills,
        )
        for a in run.agents
    ]

    extra_instruction_paths = (
        [integration.instruction_path] if integration.instruction_path else []
    )

    kwargs = {}
    if run.n_attempts is not None:
        kwargs["n_attempts"] = run.n_attempts

    return JobConfig(
        job_name=run.job_name,
        n_concurrent_trials=run.n_concurrent_trials or DEFAULT_N_CONCURRENT_TRIALS,
        tasks=run.tasks,
        datasets=run.datasets,
        agents=agents,
        environment=EnvironmentConfig(**DEFAULT_ENVIRONMENT),
        verifier=VerifierConfig(env={"EVAL_VARIANT": integration.eval_variant}),
        extra_instruction_paths=extra_instruction_paths,
        **kwargs,
    )
