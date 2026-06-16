from pathlib import Path

from harbor.models.task.config import MCPServerConfig
from pydantic import BaseModel, Field


class ConnectorCell(BaseModel):
    """One (connector, channel) cell - the tool-access strategy for a single
    connector. Lives at connectors/<connector>/<channel>/ with cell.yaml +
    sibling instruction.md (+ optional setup.sh / teardown.sh / skills/).

    A run picks a channel and a set of connectors; build_job_config concats
    the cells into the final agent + verifier wiring.
    """

    connector: str
    channel: str
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    skills: list[Path] = Field(default_factory=list)
    instruction_path: Path | None = None
    setup_script_path: Path | None = None
    teardown_script_path: Path | None = None
    environment_env: dict[str, str] = Field(default_factory=dict)
    setup_env: dict[str, str] = Field(default_factory=dict)
    teardown_env: dict[str, str] = Field(default_factory=dict)
