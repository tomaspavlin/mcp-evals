from harbor.models.job.config import JobConfig
from harbor.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    VerifierConfig,
)
from harbor.utils.env import resolve_env_vars

from mcp_evals._patches.integration_setup_script import set_setup_script
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
    mcp_servers / skills / instruction append / verifier env and the
    env-var passthrough hoisted out of per-task task.toml.
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

    # Harbor's job-level env is not template-resolved (only task-level is, via
    # base.py:_maybe_resolve_task_env), so resolve `${VAR}` here against the
    # host environment before injecting.
    environment_env = resolve_env_vars(integration.environment_env)
    setup_env = resolve_env_vars(integration.setup_env)
    # MCP_EVALS_INTEGRATION lets downstream consumers (dashboard, metrics) read
    # the integration name from trial config instead of regex-scanning job names.
    verifier_env = {
        **resolve_env_vars(integration.verifier_env),
        "MCP_EVALS_INTEGRATION": integration.name,
    }

    set_setup_script(
        integration.setup_script_path.read_text()
        if integration.setup_script_path is not None
        else None,
        env=setup_env,
    )

    kwargs = {}
    if run.n_attempts is not None:
        kwargs["n_attempts"] = run.n_attempts
    if run.job_name is not None:
        kwargs["job_name"] = run.job_name
    if run.jobs_dir is not None:
        kwargs["jobs_dir"] = run.jobs_dir

    return JobConfig(
        n_concurrent_trials=run.n_concurrent_trials or DEFAULT_N_CONCURRENT_TRIALS,
        tasks=run.tasks,
        datasets=run.datasets,
        agents=agents,
        environment=EnvironmentConfig(
            env=environment_env,
            **{**DEFAULT_ENVIRONMENT, **({"type": run.environment_type} if run.environment_type else {})},
        ),
        verifier=VerifierConfig(env=verifier_env),
        extra_instruction_paths=extra_instruction_paths,
        **kwargs,
    )
