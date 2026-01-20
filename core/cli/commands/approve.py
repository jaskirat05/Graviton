"""
Approval Commands

Handle pending approval requests.
"""

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from ..client import GatewayClient
from ..display import display_error, display_success, display_approval_list

console = Console()
app = typer.Typer(help="Manage approval requests")


@app.command("list")
def list_approvals(
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
):
    """List all pending approval requests"""
    try:
        asyncio.run(_list_approvals(gateway))
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _list_approvals(gateway: str):
    client = GatewayClient(gateway)
    try:
        result = await client.list_pending_approvals()
        approvals = result.get("pending_requests", [])
        display_approval_list(approvals)
    finally:
        await client.close()


@app.command("show")
def show_approval(
    token: str = typer.Argument(..., help="Approval request token"),
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
):
    """Show details of an approval request"""
    try:
        asyncio.run(_show_approval(token, gateway))
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _show_approval(token: str, gateway: str):
    client = GatewayClient(gateway)
    try:
        approval = await client.get_approval(token)

        console.print()
        console.print(Panel(f"Approval Request: {token[:20]}...", style="bold"))
        console.print(f"[cyan]Chain ID:[/cyan]  {approval.get('chain_id', '-')}")
        console.print(f"[cyan]Step ID:[/cyan]   {approval.get('step_id', '-')}")
        console.print(f"[cyan]Workflow:[/cyan]  {approval.get('workflow', '-')}")
        console.print(f"[cyan]Status:[/cyan]    {approval.get('status', '-')}")

        # Artifacts if any
        artifacts = approval.get("artifacts", [])
        if artifacts:
            console.print(f"\n[cyan]Artifacts:[/cyan]")
            for artifact in artifacts:
                console.print(f"  - {artifact.get('filename', '-')} ({artifact.get('type', '-')})")

        # Editable parameters
        params = approval.get("editable_parameters", {})
        if params:
            console.print(f"\n[cyan]Editable Parameters:[/cyan]")
            for key, value in params.items():
                console.print(f"  {key}: {value}")

        console.print()
    finally:
        await client.close()


@app.command("accept")
def accept_approval(
    token: str = typer.Argument(..., help="Approval request token"),
    decided_by: str = typer.Option(
        "cli-user",
        "--by",
        help="Who is making this decision",
    ),
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
):
    """Accept/approve a pending request"""
    try:
        asyncio.run(_accept_approval(token, decided_by, gateway))
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _accept_approval(token: str, decided_by: str, gateway: str):
    client = GatewayClient(gateway)
    try:
        result = await client.approve_request(token, decided_by)
        display_success(f"Approved by {decided_by}")
        console.print(f"[dim]Chain will continue execution[/dim]")
    finally:
        await client.close()


@app.command("reject")
def reject_approval(
    token: str = typer.Argument(..., help="Approval request token"),
    decided_by: str = typer.Option(
        "cli-user",
        "--by",
        help="Who is making this decision",
    ),
    from_step: Optional[str] = typer.Option(
        None,
        "--from-step",
        "-f",
        help="Step to regenerate from",
    ),
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
):
    """Reject a pending request (optionally regenerate from a step)"""
    try:
        asyncio.run(_reject_approval(token, decided_by, from_step, gateway))
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _reject_approval(
    token: str, decided_by: str, from_step: Optional[str], gateway: str
):
    client = GatewayClient(gateway)
    try:
        result = await client.reject_request(token, decided_by, from_step)
        display_success(f"Rejected by {decided_by}")

        if from_step:
            new_chain_id = result.get("new_chain_id")
            console.print(f"[dim]Regenerating from step: {from_step}[/dim]")
            if new_chain_id:
                console.print(f"[dim]New chain ID: {new_chain_id}[/dim]")
    finally:
        await client.close()
