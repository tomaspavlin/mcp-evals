"""Helpers to figure out which (connector, channel) cells a run needs.

Connectors can come from `RunConfig.connectors` directly, or be auto-resolved
by reading `[mcp_evals].connectors` from each task's task.toml. Channel comes
from `RunConfig.channel` (one channel for every connector) with optional
per-connector overrides via `RunConfig.connector_channels`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from mcp_evals.config import RunConfig
from mcp_evals.connectors.materialize import discover_dataset_task_paths


def read_task_connectors(task_path: Path) -> list[str]:
    """Read `[mcp_evals].connectors` from task_path/task.toml, or []."""
    toml_path = task_path / "task.toml"
    if not toml_path.is_file():
        return []
    data = tomllib.loads(toml_path.read_text())
    return list((data.get("mcp_evals") or {}).get("connectors") or [])


def run_task_paths(run: RunConfig) -> list[Path]:
    paths = [tc.path for tc in run.tasks if tc.path is not None]
    for ds in run.datasets:
        if ds.path is not None:
            paths.extend(discover_dataset_task_paths(ds.path))
    return paths


def resolve_connectors(run: RunConfig) -> list[str]:
    """Connector list for the run, in stable order.

    Precedence: explicit `run.connectors` > union of per-task `[mcp_evals].connectors`.
    """
    if run.connectors:
        return list(run.connectors)
    seen: set[str] = set()
    out: list[str] = []
    for tp in run_task_paths(run):
        for c in read_task_connectors(tp):
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def resolve_connector_channels(
    run: RunConfig, connectors: list[str]
) -> dict[str, str]:
    """Map each connector to its channel. Per-connector override > run.channel."""
    out: dict[str, str] = {}
    for c in connectors:
        ch = run.connector_channels.get(c) or run.channel
        if not ch:
            raise ValueError(
                f"No channel resolved for connector '{c}': set RunConfig.channel "
                f"or RunConfig.connector_channels['{c}']"
            )
        out[c] = ch
    return out
