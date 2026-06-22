"""Helpers to figure out which (app, connector) cells a run needs.

Apps can come from `RunConfig.apps` directly, or be auto-resolved
by reading `[mcp_evals].apps` from each task's task.toml. Connector comes
from `RunConfig.connector` (one connector for every app) with optional
per-app overrides via `RunConfig.app_connectors`.
"""

from __future__ import annotations

import tomllib
from fnmatch import fnmatch
from pathlib import Path

from mcp_evals.config import RunConfig
from mcp_evals.apps.materialize import discover_dataset_task_paths


def read_task_apps(task_path: Path) -> list[str]:
    """Read `[mcp_evals].apps` from task_path/task.toml, or []."""
    toml_path = task_path / "task.toml"
    if not toml_path.is_file():
        return []
    data = tomllib.loads(toml_path.read_text())
    return list((data.get("mcp_evals") or {}).get("apps") or [])


def run_task_paths(run: RunConfig) -> list[Path]:
    paths = [tc.path for tc in run.tasks if tc.path is not None]
    for ds in run.datasets:
        if ds.path is None:
            continue
        for p in discover_dataset_task_paths(ds.path):
            name = p.name
            if ds.task_names and not any(fnmatch(name, pat) for pat in ds.task_names):
                continue
            if ds.exclude_task_names and any(
                fnmatch(name, pat) for pat in ds.exclude_task_names
            ):
                continue
            paths.append(p)
    return paths


def resolve_apps(run: RunConfig) -> list[str]:
    """App list for the run, in stable order.

    Precedence: explicit `run.apps` > union of per-task `[mcp_evals].apps`.
    """
    if run.apps:
        return list(run.apps)
    seen: set[str] = set()
    out: list[str] = []
    for tp in run_task_paths(run):
        for c in read_task_apps(tp):
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def resolve_app_connectors(
    run: RunConfig, apps: list[str]
) -> dict[str, str]:
    """Map each app to its connector. Per-app override > run.connector."""
    out: dict[str, str] = {}
    for c in apps:
        ch = run.app_connectors.get(c) or run.connector
        if not ch:
            raise ValueError(
                f"No connector resolved for app '{c}': set RunConfig.connector "
                f"or RunConfig.app_connectors['{c}']"
            )
        out[c] = ch
    return out
