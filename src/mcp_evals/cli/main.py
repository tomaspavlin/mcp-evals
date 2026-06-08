import typer

from mcp_evals.cli.materialize import materialize_command
from mcp_evals.cli.run import run_command

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback()
def main() -> None:
    """mcp-evals CLI."""


app.command(name="run", help="Run a job from an mcp-evals RunConfig.")(run_command)
app.command(
    name="materialize",
    help="Copy an integration's environment/ into each task's environment/ dir.",
)(materialize_command)
