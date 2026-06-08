from pathlib import Path

import yaml
from harbor.models.job.config import DatasetConfig
from harbor.models.trial.config import TaskConfig
from pydantic import BaseModel, Field


class RunAgentConfig(BaseModel):
    """Thin per-agent config. integration provides mcp_servers/skills; user just
    picks the harness + model and optionally overrides agent kwargs."""

    name: str
    model_name: str | None = None
    kwargs: dict | None = None


class RunConfig(BaseModel):
    """Our own thin config schema. Expanded to a harbor JobConfig at runtime by
    job_builder.build_job_config(). `integration` and `agents` are typed as
    optional because the CLI can supply them via flags; the CLI validates that
    they're set before calling build_job_config()."""

    job_name: str | None = None
    integration: str | None = None
    n_concurrent_trials: int | None = None
    n_attempts: int | None = None
    tasks: list[TaskConfig] = Field(default_factory=list)
    datasets: list[DatasetConfig] = Field(default_factory=list)
    agents: list[RunAgentConfig] = Field(default_factory=list)


def load_run_config(path: Path) -> RunConfig:
    return RunConfig.model_validate(yaml.safe_load(path.read_text()))
