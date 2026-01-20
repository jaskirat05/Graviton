"""
Execute Command

Execute a workflow chain from a YAML file.
"""

import asyncio
import json
from pathlib import Path
from typing import Optional, Dict, Set

import httpx
import httpx_sse
import typer
import yaml
from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.layout import Layout
from rich.text import Text

from ..client import GatewayClient
from ..display import (
    display_error,
    display_success,
    display_warning,
    display_info,
    display_dim,
    display_chain_started,
    display_chain_result,
    display_step_completed,
    display_regenerating,
    console,
)



def _find_changed_steps(old_chain: dict, new_chain: dict) -> tuple[list[str], dict]:
    """
    Compare two chain definitions and find which steps changed.

    Returns:
        - List of changed step IDs in definition order
        - Dict of new parameters for each changed step
    """
    old_steps = {s["id"]: s for s in old_chain.get("steps", [])}
    new_steps = {s["id"]: s for s in new_chain.get("steps", [])}

    changed = []
    new_parameters = {}

    # Check each step in new chain
    for step_id, new_step in new_steps.items():
        old_step = old_steps.get(step_id)

        if not old_step:
            # New step added
            changed.append(step_id)
            new_parameters[step_id] = new_step.get("parameters", {})
        elif old_step != new_step:
            # Step changed - collect new parameters
            changed.append(step_id)
            new_params = new_step.get("parameters", {})
            old_params = old_step.get("parameters", {})

            # Only include changed parameters
            param_diff = {}
            for key, value in new_params.items():
                if old_params.get(key) != value:
                    param_diff[key] = value

            if param_diff:
                new_parameters[step_id] = param_diff

    # Return in definition order
    step_order = [s["id"] for s in new_chain.get("steps", [])]
    ordered_changed = [s for s in step_order if s in changed]

    return ordered_changed, new_parameters


class ChainProgressTracker:
    """Tracks chain execution progress for display"""

    def __init__(self, total_steps: int, step_ids: list[str] = None):
        self.total_steps = total_steps
        self.step_ids = step_ids or []
        self.completed_steps: Set[str] = set()
        self.current_step: Optional[str] = None
        self.status = "running"
        self.events: list[str] = []  # Recent events log

    def step_completed(self, step_id: str):
        self.completed_steps.add(step_id)
        self.events.append(f"[green]✓[/green] Step [cyan]{step_id}[/cyan] completed")

    def step_waiting(self, step_id: str):
        self.current_step = step_id
        self.events.append(f"[yellow]⏳[/yellow] Step [cyan]{step_id}[/cyan] waiting for approval")

    def chain_completed(self):
        self.status = "completed"
        self.events.append("[green bold]✓ Chain completed successfully[/green bold]")

    def chain_failed(self, error: str):
        self.status = "failed"
        self.events.append(f"[red bold]✗ Chain failed:[/red bold] {error}")

    @property
    def progress_ratio(self) -> float:
        if self.total_steps == 0:
            return 0
        return len(self.completed_steps) / self.total_steps

    def render(self) -> Panel:
        """Render the progress display"""
        # Build progress bar manually
        completed = len(self.completed_steps)
        total = self.total_steps
        pct = int(self.progress_ratio * 100)

        # Progress bar characters
        bar_width = 30
        filled = int(bar_width * self.progress_ratio)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Status indicator
        if self.status == "completed":
            status_icon = "[green]✓[/green]"
            status_text = "Completed"
        elif self.status == "failed":
            status_icon = "[red]✗[/red]"
            status_text = "Failed"
        elif self.current_step:
            status_icon = "[yellow]⏳[/yellow]"
            status_text = f"Waiting: {self.current_step}"
        else:
            status_icon = "[blue]⚡[/blue]"
            status_text = "Running"

        progress_line = Text.from_markup(
            f"{status_icon} {status_text}  [cyan]{bar}[/cyan]  {completed}/{total} steps ({pct}%)"
        )

        return Panel(
            progress_line,
            title="[bold]Chain Progress[/bold]",
            border_style="blue" if self.status == "running" else ("green" if self.status == "completed" else "red"),
            padding=(0, 1),
        )


def execute_cmd(
    chain_file: Path = typer.Argument(
        ...,
        help="Path to chain YAML file",
        exists=True,
        readable=True,
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        "-w",
        help="Monitor execution in real-time",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Wait for completion and show result",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force re-execution even if cached result exists",
    ),
    gateway: str = typer.Option(
        "http://localhost:8001",
        "--gateway",
        "-g",
        envvar="COMFY_CHAIN_GATEWAY",
        help="Gateway URL",
    ),
):
    """Execute a workflow chain from a YAML file"""

    # Load YAML
    try:
        with open(chain_file) as f:
            chain_def = yaml.safe_load(f)
    except Exception as e:
        display_error(f"Failed to load chain file: {e}")
        raise typer.Exit(1)

    if not chain_def:
        display_error("Chain file is empty")
        raise typer.Exit(1)

    chain_name = chain_def.get("name", "unnamed")
    steps = chain_def.get("steps", [])

    display_info("Chain", chain_name)
    display_info("Steps", str(len(steps)))

    # Execute
    try:
        asyncio.run(_execute_chain(chain_def, chain_file, gateway, watch, wait, force))
    except KeyboardInterrupt:
        display_warning("Interrupted")
        raise typer.Exit(130)
    except Exception as e:
        display_error(str(e))
        raise typer.Exit(1)


async def _execute_chain(
    chain_def: dict, chain_file: Path, gateway: str, watch: bool, wait: bool, force: bool
):
    """Async chain execution with one-chain-one-signature rule.

    Rules:
    - One YAML file = One signature (permanent lineage ID, set once, never updated)
    - No signature → first run, generate signature, save to YAML, execute fresh
    - Signature exists → find latest completed chain with this signature, diff, regenerate
    - Multiple chain executions share same signature but have different versions
    """
    client = GatewayClient(gateway)

    try:
        # Get chain content (excluding signature field for comparison)
        chain_content = {k: v for k, v in chain_def.items() if k != "signature"}
        signature = chain_def.get("signature")

        # CASE 1: Signature exists - diff against latest completed and regenerate
        if signature and not force:
            display_dim(f"Signature: {signature[:16]}...")

            try:
                # Find latest completed chain with this signature
                chain_info = await client.get_chain_by_hash(signature)
                stored_definition = chain_info.get("chain_definition")
                latest_completed = chain_info.get("latest_completed")

                if stored_definition and latest_completed:
                    # Diff current content vs stored definition
                    changed_steps, new_parameters = _find_changed_steps(stored_definition, chain_content)

                    if not changed_steps:
                        # No changes - return cached result
                        display_success("No changes detected, using cached result")
                        console.print(Panel(
                            f"[green bold]Cached Result[/green bold]\n\n"
                            f"[cyan]Chain ID:[/cyan] {latest_completed.get('chain_id')}\n"
                            f"[cyan]Job ID:[/cyan] {latest_completed.get('job_id')}\n"
                            f"[cyan]Version:[/cyan] {latest_completed.get('version', 'N/A')}\n"
                            f"[cyan]Completed:[/cyan] {latest_completed.get('completed_at', 'N/A')}\n\n"
                            f"[dim]Use --force to re-execute[/dim]",
                            title="[green]Cache Hit[/green]",
                            border_style="green"
                        ))
                        if watch or wait:
                            final_result = await client.get_result(latest_completed.get("job_id"))
                            display_chain_result(final_result)
                        return

                    # Changes detected - regenerate from first changed step
                    first_changed = changed_steps[0]
                    display_regenerating(
                        first_changed,
                        changed_steps,
                        list(new_parameters.keys()) if new_parameters else None
                    )

                    result = await client.regenerate_chain(
                        definition_hash=signature,
                        from_step=first_changed,
                        new_parameters=new_parameters,
                        chain_definition=chain_content,  # Pass current definition, not stored
                    )

                    await _handle_result(client, result, watch, wait, chain_content)
                    return

                else:
                    # Signature exists but no completed chain found - execute fresh
                    display_warning("No completed chain found for signature, executing fresh")

            except Exception as e:
                display_warning(f"Could not fetch chain by signature: {e}")
                display_dim("Executing fresh")

        # CASE 2: No signature - first run, generate and save signature
        elif not signature:
            # Generate signature from content hash (set once, never changes)
            signature = await client.calculate_hash(chain_content)
            chain_def["signature"] = signature
            _save_signature(chain_file, chain_def)
            display_success(f"Generated signature: {signature[:16]}...")

        # CASE 3: Force flag - ignore signature, execute fresh
        if force and chain_def.get("signature"):
            display_dim("Force flag set, re-executing")

        # Execute fresh
        result = await client.execute_chain(chain_content, force=force)
        await _handle_result(client, result, watch, wait, chain_content)

    finally:
        await client.close()


def _save_signature(chain_file: Path, chain_def: dict):
    """Save updated signature to YAML file"""
    try:
        with open(chain_file, "w") as f:
            yaml.dump(chain_def, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        display_warning(f"Could not save signature: {e}")


async def _handle_result(client: GatewayClient, result: dict, watch: bool, wait: bool, chain_def: dict):
    """Handle execution/regeneration result"""
    if result.get("cached"):
        console.print()
        console.print(Panel(
            f"[green bold]Cached Result Found[/green bold]\n\n"
            f"[cyan]Chain ID:[/cyan] {result.get('chain_id')}\n"
            f"[cyan]Job ID:[/cyan] {result.get('job_id')}\n"
            f"[cyan]Completed:[/cyan] {result.get('completed_at', 'N/A')}\n\n"
            f"[dim]Use --force to re-execute[/dim]",
            title="[green]Cache Hit[/green]",
            border_style="green"
        ))
        if watch or wait:
            final_result = await client.get_result(result.get("job_id"))
            display_chain_result(final_result)
        return

    chain_id = result.get("chain_id")
    job_id = result.get("job_id")
    chain_name = result.get("chain_name", "unnamed")
    total_steps = result.get("total_steps", len(chain_def.get("steps", [])))

    display_chain_started(chain_id, chain_name, total_steps)

    if watch:
        await _monitor_chain(client, chain_id, job_id, total_steps)
    elif wait:
        display_dim("Waiting for completion...")
        final_result = await client.get_result(job_id)
        display_chain_result(final_result)
    else:
        display_dim(f"Use 'comfy-chain status {job_id}' to check progress")


async def _monitor_chain(client: GatewayClient, chain_id: str, job_id: str, total_steps: int = 0):
    """Monitor chain execution via SSE - real-time push notifications

    Args:
        client: Gateway client
        chain_id: Database chain ID for SSE subscription
        job_id: Temporal job ID for result queries
        total_steps: Total number of steps in the chain
    """
    gateway_url = client.base_url
    url = f"{gateway_url}/chains/events?chain_id={chain_id}"

    # Initialize progress tracker
    tracker = ChainProgressTracker(total_steps)

    display_dim(f"Watching chain {chain_id}...")
    console.print()

    # Use Live display for sticky progress bar
    with Live(tracker.render(), console=console, refresh_per_second=4, transient=False) as live:
        try:
            async with httpx.AsyncClient(timeout=None) as http:
                async with httpx_sse.aconnect_sse(http, "GET", url) as sse:
                    async for event in sse.aiter_sse():
                        try:
                            data = json.loads(event.data)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.event or data.get("type", "unknown")

                        if event_type == "approval_requested":
                            step_id = data.get('step_id', 'unknown')
                            workflow_name = data.get('workflow', 'unknown')
                            token = data.get('token')
                            artifact_url = data.get('artifact_url', 'N/A')

                            # Update tracker
                            tracker.step_waiting(step_id)
                            live.update(tracker.render())

                            # Stop live display for interactive prompt
                            live.stop()

                            console.print()
                            console.print(Panel(
                                f"[yellow bold]Approval Required[/yellow bold]\n\n"
                                f"[cyan]Step:[/cyan] {step_id}\n"
                                f"[cyan]Workflow:[/cyan] {workflow_name}\n\n"
                                f"[dim]View artifact:[/dim] {artifact_url}",
                                title="[yellow]Action Needed[/yellow]",
                                border_style="yellow"
                            ))

                            # Interactive approval prompt
                            if token:
                                await _handle_approval_prompt(client, token, step_id)

                            # Clear waiting state and resume live display
                            tracker.current_step = None
                            console.print()
                            live.start()
                            live.update(tracker.render())

                        elif event_type == "step_completed":
                            step_id = data.get("step_id", "unknown")
                            tracker.step_completed(step_id)
                            live.update(tracker.render())
                            # Print event above progress bar
                            live.console.print(f"[green]✓[/green] Step [cyan]{step_id}[/cyan] completed")

                        elif event_type == "chain_completed":
                            tracker.chain_completed()
                            live.update(tracker.render())
                            live.console.print()
                            live.console.print(f"[green bold]✓ Chain completed successfully[/green bold]")
                            break

                        elif event_type == "chain_failed":
                            error = data.get("error", "Unknown error")
                            tracker.chain_failed(error)
                            live.update(tracker.render())
                            live.console.print()
                            live.console.print(f"[red bold]✗ Chain failed:[/red bold] {error}")
                            break

        except httpx.ConnectError:
            live.stop()
            display_error(f"Failed to connect to gateway at {gateway_url}")
            display_dim("Make sure the gateway is running and Redis is available")
        except Exception as e:
            live.stop()
            display_error(f"Error monitoring chain: {e}")

    # Fetch and display final result using job_id
    console.print()
    try:
        final_result = await client.get_result(job_id)
        display_chain_result(final_result)
    except Exception:
        pass  # Already showed status via SSE


async def _handle_approval_prompt(client: GatewayClient, token: str, step_id: str):
    """Handle interactive approval/rejection prompt"""
    try:
        # Ask user for decision
        console.print()
        choice = Prompt.ask(
            "[bold]Decision[/bold] [dim](a)pprove / (r)eject / (s)kip[/dim]",
            choices=["a", "r", "s"],
            default="s",
            show_choices=False,
        )

        if choice == "s":
            display_dim("Skipped - use approval URL to decide later")
            return

        if choice == "a":
            # Approve
            result = await client.approve_request(token, decided_by="cli-user")
            display_step_completed(step_id + " approved")

        elif choice == "r":
            # Reject - optionally with new parameters
            display_dim("Rejecting will trigger regeneration")

            # Fetch and display editable parameters
            try:
                params_info = await client.get_approval_parameters(token)
                parameters = params_info.get("parameters", [])

                if parameters:
                    console.print()
                    display_info("Editable parameters for", params_info.get('workflow_name', 'unknown'))
                    params_table = Table(show_header=True, header_style="bold")
                    params_table.add_column("Key")
                    params_table.add_column("Current Value")
                    params_table.add_column("Type")
                    params_table.add_column("Category")

                    for param in parameters:
                        current_value = param.get("current_value", "N/A")
                        params_table.add_row(
                            param.get("key", "?"),
                            str(current_value)[:50],  # Truncate long values
                            param.get("type", "str"),
                            param.get("category", "-")
                        )
                    console.print(params_table)
                    console.print()
            except Exception as e:
                display_dim(f"Could not fetch editable parameters: {e}")

            # Ask if they want to provide new parameters
            with_params = Confirm.ask("Provide new parameters?", default=False)

            new_params = {}
            if with_params:
                display_dim("Enter parameters as key=value (empty line to finish):")
                while True:
                    param_input = Prompt.ask("Parameter", default="")
                    if not param_input:
                        break
                    if "=" in param_input:
                        key, value = param_input.split("=", 1)
                        # Try to parse as JSON, otherwise keep as string
                        try:
                            new_params[key.strip()] = json.loads(value.strip())
                        except json.JSONDecodeError:
                            new_params[key.strip()] = value.strip()
                    else:
                        display_error("Invalid format. Use key=value")

            # Submit rejection with error handling for validation
            try:
                result = await client.reject_request(
                    token,
                    decided_by="cli-user",
                    new_parameters=new_params if new_params else None
                )
                display_warning(f"Step {step_id} rejected, regenerating...")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    # Validation error - show details
                    try:
                        error_detail = e.response.json()
                        error_msg = error_detail.get("detail", str(error_detail))
                        display_error(f"Parameter validation failed: {error_msg}")
                    except json.JSONDecodeError:
                        display_error(f"Parameter validation failed: {e.response.text}")
                elif e.response.status_code == 422:
                    # Unprocessable entity - show validation errors
                    try:
                        error_detail = e.response.json()
                        display_error("Invalid request:")
                        for error in error_detail.get("detail", []):
                            loc = " -> ".join(str(x) for x in error.get("loc", []))
                            msg = error.get("msg", "Unknown error")
                            display_dim(f"  {loc}: {msg}")
                    except json.JSONDecodeError:
                        display_error(f"Invalid request: {e.response.text}")
                else:
                    raise

    except Exception as e:
        display_error(f"Failed to submit decision: {e}")
