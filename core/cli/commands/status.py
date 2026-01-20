"""
Status and Result Commands

Check chain execution status and retrieve results.
"""

import asyncio
import json
from typing import Optional

import typer
from rich.console import Console

from ..client import GatewayClient
from ..display import display_error, display_chain_status, display_chain_result

console = Console()


def status_cmd(
    chain_id: str = typer.Argument(..., help="Chain execution ID"),
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
):
    """Get current status of a chain execution"""
    try:
        asyncio.run(_get_status(chain_id, gateway, json_output))
    except KeyboardInterrupt:
        raise typer.Exit(130)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _get_status(chain_id: str, gateway: str, json_output: bool):
    client = GatewayClient(gateway)
    try:
        status = await client.get_status(chain_id)

        if json_output:
            console.print_json(json.dumps(status))
        else:
            display_chain_status(status)
    finally:
        await client.close()


def result_cmd(
    chain_id: str = typer.Argument(..., help="Chain execution ID"),
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
    wait: bool = typer.Option(
        True,
        "--wait/--no-wait",
        help="Wait for completion",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        "-j",
        help="Output as JSON",
    ),
):
    """Get final result of a chain execution"""
    try:
        asyncio.run(_get_result(chain_id, gateway, wait, json_output))
    except KeyboardInterrupt:
        raise typer.Exit(130)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _get_result(chain_id: str, gateway: str, wait: bool, json_output: bool):
    client = GatewayClient(gateway)
    try:
        if wait:
            console.print("[dim]Waiting for completion...[/dim]")

        result = await client.get_result(chain_id)

        if json_output:
            console.print_json(json.dumps(result))
        else:
            display_chain_result(result)
    finally:
        await client.close()
