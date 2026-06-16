import asyncio
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from harbor.models.job.config import DatasetConfig
from harbor.models.trial.config import TaskConfig
from rich.console import Console
from typer import Option

from mcp_evals.config import RunAgentConfig, RunConfig, load_run_config
from mcp_evals.connectors.loader import CONNECTORS_DIR, load_connector_cell
from mcp_evals.connectors.materialize import materialize_for_tasks
from mcp_evals.connectors.resolver import (
    resolve_connector_channels,
    resolve_connectors,
    run_task_paths,
)
from mcp_evals.job_builder import build_job_config

console = Console()


def run_command(
    config_path: Annotated[
        Path | None,
        Option(
            "-c",
            "--config",
            help="mcp-evals RunConfig yaml. Optional if --channel plus tasks/dataset + agent are given via flags.",
            show_default=False,
        ),
    ] = None,
    channel: Annotated[
        str | None,
        Option(
            "--channel",
            help="Access channel for connectors: mcp, cli, mcpc, skill (overrides the value in the config).",
            show_default=False,
        ),
    ] = None,
    connectors: Annotated[
        list[str] | None,
        Option(
            "--connector",
            help="Connector name (repeatable). If omitted, auto-resolved from each task's [mcp_evals].connectors in task.toml.",
            show_default=False,
        ),
    ] = None,
    connectors_dir: Annotated[
        Path | None,
        Option(
            "--connectors-dir",
            help="Directory containing connectors (default: ./connectors).",
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

    if channel is not None:
        run.channel = channel
    if connectors:
        run.connectors = list(connectors)
    if connectors_dir is not None:
        run.connectors_dir = connectors_dir
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

    if not run.channel and not run.connector_channels:
        raise typer.BadParameter(
            "--channel is required (set via flag, config, or per-connector connector_channels)"
        )
    if not run.agents:
        raise typer.BadParameter("--agent is required (set via flag or config)")
    if not run.tasks and not run.datasets:
        raise typer.BadParameter(
            "--task or --dataset-path is required (set via flag or config)"
        )

    if run.job_name is None and config_path is not None:
        run.job_name = config_path.stem

    connector_names = resolve_connectors(run)
    if not connector_names:
        raise typer.BadParameter(
            "No connectors resolved. Set --connector flags, RunConfig.connectors, "
            "or `[mcp_evals].connectors` in each task.toml."
        )
    channel_map = resolve_connector_channels(run, connector_names)
    cells = [
        load_connector_cell(
            c, channel_map[c], root=run.connectors_dir or CONNECTORS_DIR
        )
        for c in connector_names
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
