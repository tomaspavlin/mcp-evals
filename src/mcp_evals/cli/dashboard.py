import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from typer import Argument, Option

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_PATH = REPO_ROOT / "dashboard" / "app.py"
VENV_STREAMLIT = REPO_ROOT / "dashboard" / ".venv" / "bin" / "streamlit"


def dashboard_command(
    jobs_dir: Annotated[
        Path,
        Argument(help="Folder containing job directories."),
    ] = Path("jobs"),
    port: Annotated[
        int,
        Option("-p", "--port", help="Port for the streamlit server."),
    ] = 8501,
    host: Annotated[
        str,
        Option("--host", help="Host to bind the server to."),
    ] = "localhost",
    no_browser: Annotated[
        bool,
        Option("--no-browser", help="Do not open a browser tab (headless mode)."),
    ] = False,
) -> None:
    """Launch the streamlit dashboard against a jobs dir.

    Example usage:
        mcp-evals dashboard                    # ./jobs
        mcp-evals dashboard evals/jobs         # an external project's jobs dir
        mcp-evals dashboard ~/x/jobs -p 9000 --host 0.0.0.0 --no-browser
    """
    jobs_dir = jobs_dir.expanduser().resolve()
    if not jobs_dir.is_dir():
        console.print(f"[red]Jobs dir not found: {jobs_dir}[/red]")
        raise typer.Exit(code=1)
    if not APP_PATH.exists():
        console.print(f"[red]Dashboard app not found: {APP_PATH}[/red]")
        raise typer.Exit(code=1)

    # Prefer the dashboard's dedicated venv (see dashboard/README.md),
    # fall back to whatever streamlit is on PATH.
    streamlit = (
        str(VENV_STREAMLIT) if VENV_STREAMLIT.exists() else shutil.which("streamlit")
    )
    if streamlit is None:
        console.print(
            "[red]streamlit not found.[/red] "
            "Set up the dashboard venv per dashboard/README.md"
        )
        raise typer.Exit(code=1)

    cmd = [
        streamlit,
        "run",
        str(APP_PATH),
        "--server.port",
        str(port),
        "--server.address",
        host,
    ]
    if no_browser:
        cmd += ["--server.headless", "true"]

    os.environ["MCP_EVALS_JOBS_DIR"] = str(jobs_dir)
    try:
        os.execv(streamlit, cmd)
    except OSError as e:
        console.print(
            f"[red]Failed to launch {streamlit}: {e}[/red]\n"
            "The dashboard venv may be broken; recreate it per dashboard/README.md"
        )
        raise typer.Exit(code=1)
