import asyncio
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from typer import Option

from mcp_evals.config import load_run_config
from mcp_evals.integrations.loader import load_integration
from mcp_evals.job_builder import build_job_config

console = Console()


def run_command(
    config_path: Annotated[
        Path,
        Option(
            "-c",
            "--config",
            help="mcp-evals RunConfig yaml.",
            show_default=False,
        ),
    ],
    integration: Annotated[
        str | None,
        Option(
            "--integration",
            help="Integration name (overrides the value in the config).",
            show_default=False,
        ),
    ] = None,
    job_name: Annotated[
        str | None,
        Option("--job-name", help="Override RunConfig.job_name.", show_default=False),
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

    run = load_run_config(config_path)
    if integration is not None:
        run.integration = integration
    if job_name is not None:
        run.job_name = job_name
    if n_concurrent is not None:
        run.n_concurrent_trials = n_concurrent

    if run.job_name is None:
        run.job_name = config_path.stem

    integ = load_integration(run.integration)
    job_config = build_job_config(run, integ)

    if n_attempts is not None:
        job_config.n_attempts = n_attempts

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
