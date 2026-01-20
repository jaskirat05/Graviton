"""
Rich Display Helpers

Formatting functions for CLI output using Rich.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from typing import Dict, Any, Optional

console = Console()


def display_error(message: str):
    """Display an error message"""
    console.print(f"[red]Error:[/red] {message}")


def display_success(message: str):
    """Display a success message"""
    console.print(f"[green]✓[/green] {message}")


def display_warning(message: str):
    """Display a warning message"""
    console.print(f"[yellow]Warning:[/yellow] {message}")


def display_info(label: str, value: str):
    """Display an info line"""
    console.print(f"[cyan]{label}:[/cyan] {value}")


def display_dim(message: str):
    """Display a dimmed message"""
    console.print(f"[dim]{message}[/dim]")


def display_step_completed(step_id: str):
    """Display step completion"""
    console.print(f"[green]✓[/green] Step [cyan]{step_id}[/cyan] completed")


def display_regenerating(from_step: str, changed_steps: list[str], params: list[str] = None):
    """Display regeneration info"""
    console.print(f"[cyan]Changed steps:[/cyan] {', '.join(changed_steps)}")
    console.print(f"[cyan]Regenerating from:[/cyan] {from_step}")
    if params:
        console.print(f"[dim]Parameters to update: {params}[/dim]")


def display_chain_started(chain_id: str, chain_name: str, total_steps: int):
    """Display chain started message"""
    console.print()
    console.print(f"[green]✓[/green] Chain started")
    console.print(f"  [dim]Chain ID:[/dim]   {chain_id}")
    console.print(f"  [dim]Name:[/dim]       {chain_name}")
    console.print(f"  [dim]Steps:[/dim]      {total_steps}")
    console.print()


def display_chain_status(status: Dict[str, Any]):
    """Display chain status as a Rich table"""
    table = Table(title=f"Chain Status: {status.get('chain_id', 'unknown')}")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    step_results = status.get("step_results", {})
    if not step_results:
        # Fallback for different response format
        step_results = status.get("steps", {})

    for step_id, step_data in step_results.items():
        step_status = step_data.get("status", "pending")
        status_display = _format_status(step_status)
        details = step_data.get("error", "") or ""
        table.add_row(step_id, status_display, details[:50])

    console.print(table)

    # Overall status
    overall = status.get("status", "unknown")
    console.print(f"\n[dim]Overall:[/dim] {_format_status(overall)}")


def display_chain_result(result: Dict[str, Any]):
    """Display final chain result"""
    chain_name = result.get("chain_name", "unknown")
    status = result.get("status", "unknown")

    console.print()
    console.print(Panel(f"Chain: {chain_name}", style="bold"))

    # Status with color
    status_display = _format_status(status)
    console.print(f"Status: {status_display}")

    # Step results table
    table = Table(title="Step Results")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Workflow")

    for step_id, step_data in result.get("step_results", {}).items():
        step_status = step_data.get("status", "unknown")
        workflow = step_data.get("workflow", "-")
        table.add_row(step_id, _format_status(step_status), workflow)

    console.print(table)

    # Errors if any
    if result.get("error"):
        console.print(f"\n[red]Error:[/red] {result['error']}")

    # Failed steps
    failed = result.get("failed_steps", [])
    if failed:
        console.print(f"\n[red]Failed steps:[/red] {', '.join(failed)}")


def display_approval_list(approvals: list):
    """Display list of pending approvals"""
    if not approvals:
        console.print("[dim]No pending approvals[/dim]")
        return

    table = Table(title="Pending Approvals")
    table.add_column("Token", style="cyan")
    table.add_column("Step")
    table.add_column("Chain")
    table.add_column("Created")

    for approval in approvals:
        table.add_row(
            approval.get("token", "-")[:12] + "...",
            approval.get("step_id", "-"),
            approval.get("chain_id", "-")[:12] + "...",
            approval.get("created_at", "-"),
        )

    console.print(table)


def display_health(health: Dict[str, Any]):
    """Display gateway health status"""
    status = health.get("status", "unknown")
    version = health.get("version", "unknown")
    temporal = health.get("temporal_connected", False)

    status_style = "[green]" if status == "healthy" else "[red]"
    temporal_style = "[green]✓" if temporal else "[red]✗"

    console.print()
    console.print(f"Gateway Status: {status_style}{status}[/]")
    console.print(f"Version:        {version}")
    console.print(f"Temporal:       {temporal_style}[/] {'connected' if temporal else 'disconnected'}")
    console.print()


def _format_status(status: str) -> str:
    """Format status with appropriate color"""
    styles = {
        "completed": "[green]completed[/green]",
        "success": "[green]success[/green]",
        "running": "[yellow]running[/yellow]",
        "in_progress": "[yellow]in progress[/yellow]",
        "pending": "[dim]pending[/dim]",
        "failed": "[red]failed[/red]",
        "error": "[red]error[/red]",
        "waiting_approval": "[magenta]awaiting approval[/magenta]",
    }
    return styles.get(status, f"[dim]{status}[/dim]")


def create_progress() -> Progress:
    """Create a progress bar for chain monitoring"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    )
