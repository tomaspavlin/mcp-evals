import typer

from connector_evals.cli.dashboard import dashboard_command
from connector_evals.cli.materialize import materialize_command
from connector_evals.cli.run import run_command

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback()
def main() -> None:
    """connector-evals CLI."""


app.command(name="run", help="Run a job from an connector-evals RunConfig.")(run_command)
app.command(
    name="materialize",
    help="Copy the shared base image dir into each task's environment/ dir.",
)(materialize_command)
app.command(
    name="dashboard",
    help="Launch the streamlit dashboard against a jobs dir.",
)(dashboard_command)
