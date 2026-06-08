from pathlib import Path

from harbor.models.task.config import MCPServerConfig
from pydantic import BaseModel, Field


class Integration(BaseModel):
    """Bundles the (MCP servers | skills | instruction append | EVAL_VARIANT)
    tuple that distinguishes one tool-access strategy from another for the same
    underlying tasks. Lives at integrations/<name>/integration.yaml with a
    sibling instruction.md.
    """

    name: str
    eval_variant: str
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    skills: list[Path] = Field(default_factory=list)
    instruction_path: Path | None = None
    environment_dir: Path | None = None
    environment_env: dict[str, str] = Field(default_factory=dict)
    verifier_env: dict[str, str] = Field(default_factory=dict)
