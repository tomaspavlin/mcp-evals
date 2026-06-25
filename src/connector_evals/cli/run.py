import asyncio
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from harbor.models.job.config import DatasetConfig
from harbor.models.trial.config import TaskConfig
from rich.console import Console
from typer import Option

from connector_evals.config import RunAgentConfig, RunConfig, load_run_config
from connector_evals.apps.loader import APPS_DIR, load_app_cell
from connector_evals.apps.materialize import materialize_for_tasks
from connector_evals.apps.resolver import (
    resolve_app_connectors,
    resolve_apps,
    run_task_paths,
)
from connector_evals.job_builder import build_job_config

console = Console()


def run_command(
    config_path: Annotated[
        Path | None,
        Option(
            "-c",
            "--config",
            help="connector-evals RunConfig yaml. Optional if --connector plus tasks/dataset + agent are given via flags.",
            show_default=False,
        ),
    ] = None,
    connector: Annotated[
        str | None,
        Option(
            "--connector",
            help="Access connector for apps: mcp, cli, mcpc, cli+skill (overrides the value in the config).",
            show_default=False,
        ),
    ] = None,
    apps: Annotated[
        list[str] | None,
        Option(
            "--app",
            help="App name (repeatable). If omitted, auto-resolved from each task's [connector_evals].apps in task.toml.",
            show_default=False,
        ),
    ] = None,
    apps_dir: Annotated[
        Path | None,
        Option(
            "--apps-dir",
            help="Directory containing apps (default: ./apps).",
            show_default=False,
        ),
    ] = None,
    agent: Annotated[
        str | None,
        Option(
            "-a",
            "--agent",
            help="Single agent name (replaces the agents list).",
            show_default=False,
        ),
    ] = None,
    model: Annotated[
        str | None,
        Option(
            "-m",
            "--model",
            help="Model for --agent. Omit for oracle.",
            show_default=False,
        ),
    ] = None,
    tasks: Annotated[
        list[Path] | None,
        Option(
            "-t",
            "--task",
            help="Task directory path (repeatable). Replaces RunConfig.tasks.",
            show_default=False,
        ),
    ] = None,
    dataset_path: Annotated[
        Path | None,
        Option(
            "-p",
            "--dataset-path",
            help="Dataset directory path. Replaces RunConfig.datasets.",
            show_default=False,
        ),
    ] = None,
    task_names: Annotated[
        list[str] | None,
        Option(
            "--task-name",
            help="Task-name glob filter (repeatable). Requires --dataset-path.",
            show_default=False,
        ),
    ] = None,
    exclude_task_names: Annotated[
        list[str] | None,
        Option(
            "--exclude-task-name",
            help="Task-name glob to exclude (repeatable). Requires --dataset-path.",
            show_default=False,
        ),
    ] = None,
    job_name: Annotated[
        str | None,
        Option("--job-name", help="Override RunConfig.job_name.", show_default=False),
    ] = None,
    jobs_dir: Annotated[
        Path | None,
        Option(
            "-o",
            "--jobs-dir",
            help="Directory to store job results (default: ./jobs).",
            show_default=False,
        ),
    ] = None,
    n_attempts: Annotated[
        int | None,
        Option("-k", "--n-attempts", help="Attempts per trial.", show_default=False),
    ] = None,
    n_concurrent: Annotated[
        int | None,
        Option(
            "-n", "--n-concurrent", help="Concurrent trials.", show_default=False
        ),
    ] = None,
    env: Annotated[
        str | None,
        Option(
            "--env",
            help="Sandbox backend (docker, daytona, e2b, ...). Overrides defaults.py.",
            show_default=False,
        ),
    ] = None,
    env_file: Annotated[
        Path | None,
        Option("--env-file", help="Path to a .env file to load.", show_default=False),
    ] = None,
    yes: Annotated[
        bool,
        Option("-y", "--yes", help="Auto-confirm host env access prompt."),
    ] = False,
) -> None:
    if env_file is not None:
        if not env_file.exists():
            console.print(f"[red]Env file not found: {env_file}[/red]")
            raise typer.Exit(code=1)
        load_dotenv(env_file, override=True)
    elif Path(".env").exists():
        load_dotenv(".env", override=False)

    run = load_run_config(config_path) if config_path is not None else RunConfig()

    if connector is not None:
        run.connector = connector
    if apps:
        run.apps = list(apps)
    if apps_dir is not None:
        run.apps_dir = apps_dir
    if agent is not None:
        run.agents = [RunAgentConfig(name=agent, model_name=model)]
    elif model is not None:
        raise typer.BadParameter("--model requires --agent")
    if tasks:
        run.tasks = [TaskConfig(path=p) for p in tasks]
    if dataset_path is not None:
        run.datasets = [
            DatasetConfig(
                path=dataset_path,
                task_names=task_names or [],
                exclude_task_names=exclude_task_names or [],
            )
        ]
    elif task_names or exclude_task_names:
        raise typer.BadParameter(
            "--task-name/--exclude-task-name require --dataset-path"
        )
    if job_name is not None:
        run.job_name = job_name
    if jobs_dir is not None:
        run.jobs_dir = jobs_dir
    if n_concurrent is not None:
        run.n_concurrent_trials = n_concurrent
    if n_attempts is not None:
        run.n_attempts = n_attempts
    if env is not None:
        run.environment_type = env

    if not run.connector and not run.app_connectors:
        raise typer.BadParameter(
            "--connector is required (set via flag, config, or per-app app_connectors)"
        )
    if not run.agents:
        raise typer.BadParameter("--agent is required (set via flag or config)")
    if not run.tasks and not run.datasets:
        raise typer.BadParameter(
            "--task or --dataset-path is required (set via flag or config)"
        )

    if run.job_name is None and config_path is not None:
        run.job_name = config_path.stem

    app_names = resolve_apps(run)
    if not app_names:
        raise typer.BadParameter(
            "No apps resolved. Set --app flags, RunConfig.apps, "
            "or `[connector_evals].apps` in each task.toml."
        )
    connector_map = resolve_app_connectors(run, app_names)
    cells = [
        load_app_cell(
            c, connector_map[c], root=run.apps_dir or APPS_DIR
        )
        for c in app_names
    ]

    materialize_for_tasks(run_task_paths(run))

    job_config = build_job_config(run, cells)

    asyncio.run(_execute(job_config, yes=yes))


async def _execute(job_config, *, yes: bool) -> None:
    from harbor.cli.jobs import _confirm_host_env_access, print_job_results_tables
    from harbor.job import Job

    job = await Job.create(job_config)
    _confirm_host_env_access(job, console, skip_confirm=yes)
    job_result = await job.run()

    console.print()
    print_job_results_tables(job_result)
    console.print(f"Results written to {job._job_result_path}")
    console.print(f"Inspect: `harbor view {job.job_dir.parent}`")
