"""
Health Command

Check if the gateway is running and healthy.
"""

import asyncio

import typer
from rich.console import Console

from ..client import GatewayClient
from ..display import display_error, display_health

console = Console()


def health_cmd(
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
):
    """Check if the gateway is running"""
    try:
        asyncio.run(_check_health(gateway))
    except Exception as e:
        display_error(f"Cannot connect to gateway at {gateway}")
        console.print(f"[dim]{e}[/dim]")
        raise typer.Exit(1)


async def _check_health(gateway: str):
    client = GatewayClient(gateway)
    try:
        health = await client.health()
        display_health(health)
    finally:
        await client.close()
