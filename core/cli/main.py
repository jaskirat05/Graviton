"""
ComfyChain CLI

Modern CLI for executing and monitoring workflow chains.
"""

import typer
from rich.console import Console

from .commands import execute, status, approve, health

app = typer.Typer(
    name="comfy-chain",
    help="ComfyChain CLI - Execute and monitor workflow chains",
    no_args_is_help=True,
)
console = Console()

# Register commands
app.command(name="execute")(execute.execute_cmd)
app.command(name="status")(status.status_cmd)
app.command(name="result")(status.result_cmd)
app.command(name="health")(health.health_cmd)

# Register sub-app for approve commands
app.add_typer(approve.app, name="approve")


def main():
    """Entry point for the CLI"""
    app()


if __name__ == "__main__":
    main()
