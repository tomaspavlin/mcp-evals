from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer import Option

from mcp_evals.config import load_run_config
from mcp_evals.apps.materialize import (
    discover_dataset_task_paths,
    materialize_for_tasks,
)

console = Console()


def materialize_command(
    tasks: Annotated[
        list[Path] | None,
        Option("-t", "--task", help="Task directory (repeatable).", show_default=False),
    ] = None,
    dataset_path: Annotated[
        Path | None,
        Option("-p", "--dataset-path", help="Dataset dir; materializes every task inside.", show_default=False),
    ] = None,
    config_path: Annotated[
        Path | None,
        Option("-c", "--config", help="RunConfig yaml. Reuses its tasks + datasets.", show_default=False),
    ] = None,
) -> None:
    """Copy the shared base image dir (images/base/) into each task's
    `environment/` dir. Lets `harbor run -t tasks/<name>` work standalone."""
    if config_path is not None:
        run = load_run_config(config_path)
        if not tasks:
            tasks = [tc.path for tc in run.tasks if tc.path is not None]
        if dataset_path is None and run.datasets:
            for ds in run.datasets:
                if ds.path is not None:
                    dataset_path = ds.path
                    break

    task_paths: list[Path] = list(tasks or [])
    if dataset_path is not None:
        task_paths.extend(discover_dataset_task_paths(dataset_path))

    if not task_paths:
        raise typer.BadParameter("Provide --task, --dataset-path, or --config")

    materialized = materialize_for_tasks(task_paths)
    for path in materialized:
        console.print(f"materialized {path}")
