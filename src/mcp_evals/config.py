from pathlib import Path

import yaml
from harbor.models.job.config import DatasetConfig
from harbor.models.trial.config import TaskConfig
from pydantic import BaseModel, Field


class RunAgentConfig(BaseModel):
    """Thin per-agent config. Channel + connectors provide mcp_servers/skills;
    user just picks the harness + model and optionally overrides agent kwargs."""

    name: str
    model_name: str | None = None
    kwargs: dict | None = None


class RunConfig(BaseModel):
    """Our own thin config schema. Expanded to a harbor JobConfig at runtime by
    job_builder.build_job_config().

    Tool access is split into two axes:
    - `channel`: how the agent reaches the connectors - `mcp`, `cli`, `mcpc`,
      `skill`. One channel applies to every connector by default.
    - `connectors`: which third-party services the task uses (e.g. `apify`,
      `github`). Auto-populated from `[mcp_evals].connectors` in each task's
      task.toml when not set on the run.
    - `connector_channels`: optional per-connector override of `channel`,
      for hybrid runs (e.g. github via MCP but apify via CLI).
    """

    job_name: str | None = None
    channel: str | None = None
    connectors: list[str] = Field(default_factory=list)
    connector_channels: dict[str, str] = Field(default_factory=dict)
    connectors_dir: Path | None = None
    jobs_dir: Path | None = None
    environment_type: str | None = None
    n_concurrent_trials: int | None = None
    n_attempts: int | None = None
    tasks: list[TaskConfig] = Field(default_factory=list)
    datasets: list[DatasetConfig] = Field(default_factory=list)
    agents: list[RunAgentConfig] = Field(default_factory=list)


def load_run_config(path: Path) -> RunConfig:
    return RunConfig.model_validate(yaml.safe_load(path.read_text()))
