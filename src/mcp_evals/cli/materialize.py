from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer import Argument, Option

from mcp_evals.config import load_run_config
from mcp_evals.integrations.loader import INTEGRATIONS_DIR, load_integration
from mcp_evals.integrations.materialize import (
    discover_dataset_task_paths,
    materialize_for_tasks,
)

console = Console()


def materialize_command(
    integration: Annotated[
        str | None,
        Option("--integration", help="Integration name. Required unless --config is given.", show_default=False),
    ] = None,
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
        Option("-c", "--config", help="RunConfig yaml. Reuses its integration + tasks + datasets.", show_default=False),
    ] = None,
    integrations_dir: Annotated[
        Path | None,
        Option("--integrations-dir", help="Directory containing integrations (default: ./integrations).", show_default=False),
    ] = None,
) -> None:
    """Copy integration env files into each task's `environment/` dir.

    Lets `harbor run -t tasks/<name>` work standalone (without `mcp-evals run`),
    and surfaces what would actually ship for inspection.
    """
    if config_path is not None:
        run = load_run_config(config_path)
        if integration is None:
            integration = run.integration
        if integrations_dir is None:
            integrations_dir = run.integrations_dir
        if not tasks:
            tasks = [tc.path for tc in run.tasks if tc.path is not None]
        if dataset_path is None and run.datasets:
            for ds in run.datasets:
                if ds.path is not None:
                    dataset_path = ds.path
                    break

    if integration is None:
        raise typer.BadParameter("--integration is required (or pass --config)")

    integ = load_integration(integration, root=integrations_dir or INTEGRATIONS_DIR)
    if integ.environment_dir is None:
        console.print(
            f"[yellow]Integration '{integration}' has no environment/ dir - nothing to do[/yellow]"
        )
        raise typer.Exit()

    task_paths: list[Path] = list(tasks or [])
    if dataset_path is not None:
        task_paths.extend(discover_dataset_task_paths(dataset_path))

    if not task_paths:
        raise typer.BadParameter("Provide --task, --dataset-path, or --config")

    materialized = materialize_for_tasks(integ, task_paths)
    for path in materialized:
        console.print(f"materialized {path}")
