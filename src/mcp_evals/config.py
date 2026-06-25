from pathlib import Path

import yaml
from harbor.models.job.config import DatasetConfig
from harbor.models.trial.config import TaskConfig
from pydantic import BaseModel, Field


class RunAgentConfig(BaseModel):
    """Thin per-agent config. Connector + apps provide mcp_servers/skills;
    user just picks the harness + model and optionally overrides agent kwargs."""

    name: str
    model_name: str | None = None
    kwargs: dict | None = None


class RunConfig(BaseModel):
    """Our own thin config schema. Expanded to a harbor JobConfig at runtime by
    job_builder.build_job_config().

    Tool access is split into two axes:
    - `connector`: how the agent reaches the apps - `mcp`, `cli`, `mcpc`,
      `cli+skill` (legacy alias: `skill`). One connector applies to every app
      by default.
    - `apps`: which third-party services the task uses (e.g. `apify`,
      `github`). Auto-populated from `[mcp_evals].apps` in each task's
      task.toml when not set on the run.
    - `app_connectors`: optional per-app override of `connector`,
      for hybrid runs (e.g. github via MCP but apify via CLI).
    """

    job_name: str | None = None
    connector: str | None = None
    apps: list[str] = Field(default_factory=list)
    app_connectors: dict[str, str] = Field(default_factory=dict)
    apps_dir: Path | None = None
    jobs_dir: Path | None = None
    environment_type: str | None = None
    n_concurrent_trials: int | None = None
    n_attempts: int | None = None
    tasks: list[TaskConfig] = Field(default_factory=list)
    datasets: list[DatasetConfig] = Field(default_factory=list)
    agents: list[RunAgentConfig] = Field(default_factory=list)


def load_run_config(path: Path) -> RunConfig:
    return RunConfig.model_validate(yaml.safe_load(path.read_text()))
