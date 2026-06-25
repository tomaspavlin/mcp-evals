import json
from pathlib import Path

from harbor.models.job.config import JobConfig
from harbor.models.trial.config import (
    AgentConfig,
    EnvironmentConfig,
    VerifierConfig,
)
from harbor.utils.env import resolve_env_vars

from connector_evals._patches.integration_setup_script import set_setup_script
from connector_evals._patches.integration_teardown_script import set_teardown_script
from connector_evals.config import RunConfig
from connector_evals.apps.model import AppCell
from connector_evals.defaults import (
    DEFAULT_AGENT_KWARGS,
    DEFAULT_ENVIRONMENT,
    DEFAULT_N_CONCURRENT_TRIALS,
)


def _merge_env(cells: list[AppCell], attr: str) -> dict[str, str]:
    """Merge per-cell env dicts. Conflicts on the same key are an error -
    surfacing the misconfiguration is better than picking a winner silently."""
    merged: dict[str, str] = {}
    for cell in cells:
        for k, v in getattr(cell, attr).items():
            if k in merged and merged[k] != v:
                raise ValueError(
                    f"Conflicting {attr}[{k}]: "
                    f"{merged[k]!r} vs {v!r} (from {cell.app}/{cell.connector})"
                )
            merged[k] = v
    return merged


def _strip_shebang(text: str) -> str:
    """Drop the first line if it starts with `#!`. Body shebang would otherwise
    confuse the outer concatenated script."""
    if text.startswith("#!"):
        _, _, rest = text.partition("\n")
        return rest
    return text


def _concat_scripts(paths: list[Path]) -> str | None:
    """Concatenate multiple cell setup/teardown scripts into one. Each cell's
    body runs in a subshell so a `set -e` or `exit` in one doesn't abort the
    next; the outer `set -e` still surfaces a non-zero exit loudly."""
    if not paths:
        return None
    parts = ["#!/bin/sh", "set -e"]
    for p in paths:
        parts.append(f"# --- {p.parent.parent.name}/{p.parent.name}/{p.name}")
        parts.append("(")
        parts.append(_strip_shebang(p.read_text()))
        parts.append(")")
    return "\n".join(parts) + "\n"


def build_job_config(run: RunConfig, cells: list[AppCell]) -> JobConfig:
    """Expand RunConfig + per-app cells + defaults.py into a harbor JobConfig.

    Cells are concatenated: mcp_servers/skills/instruction_paths join, env
    dicts merge (conflicts error). Setup and teardown scripts concat into one
    sequenced script. Verifier sees the per-app connector map via
    CONNECTOR_EVALS_CONNECTORS_JSON.
    """
    mcp_servers = [s for cell in cells for s in cell.mcp_servers]
    skills = [s for cell in cells for s in cell.skills]

    agents = [
        AgentConfig(
            name=a.name,
            model_name=a.model_name,
            kwargs={**DEFAULT_AGENT_KWARGS, **(a.kwargs or {})},
            mcp_servers=mcp_servers,
            skills=skills,
        )
        for a in run.agents
    ]

    extra_instruction_paths = [
        cell.instruction_path for cell in cells if cell.instruction_path is not None
    ]

    environment_env = resolve_env_vars(_merge_env(cells, "environment_env"))
    setup_env = resolve_env_vars(_merge_env(cells, "setup_env"))
    teardown_env = resolve_env_vars(_merge_env(cells, "teardown_env"))

    connectors_by_app = {c.app: c.connector for c in cells}
    verifier_env = {
        "CONNECTOR_EVALS_APPS": ",".join(connectors_by_app),
        "CONNECTOR_EVALS_CONNECTORS_JSON": json.dumps(connectors_by_app, sort_keys=True),
        # Convenience: set CONNECTOR_EVALS_CONNECTOR only when one connector covers every
        # app (the common case). Hybrid runs leave it unset; verifiers
        # should prefer CONNECTOR_EVALS_CONNECTORS_JSON.
        **(
            {"CONNECTOR_EVALS_CONNECTOR": next(iter(set(connectors_by_app.values())))}
            if len(set(connectors_by_app.values())) == 1
            else {}
        ),
    }

    set_setup_script(
        _concat_scripts(
            [c.setup_script_path for c in cells if c.setup_script_path is not None]
        ),
        env=setup_env,
    )
    set_teardown_script(
        _concat_scripts(
            [c.teardown_script_path for c in cells if c.teardown_script_path is not None]
        ),
        env=teardown_env,
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
