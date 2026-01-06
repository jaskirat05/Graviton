"""
Chain Engine

Service layer for executing workflow chains using Temporal.
"""

import uuid
from typing import Dict, Any, Optional
from pathlib import Path
from sqlalchemy import select, and_, desc
import os

from temporalio.client import Client

from .models import ExecutionGraph, StepResult, ChainExecutionResult
from ..database.session import get_session
from ..database.models import Chain, Workflow, Artifact


class ChainEngine:
    """
    Engine for executing workflow chains

    This provides a simple interface to execute chains using Temporal workflows.
    """

    def __init__(self, temporal_client: Client):
        """
        Initialize chain engine

        Args:
            temporal_client: Connected Temporal client
        """
        self.client = temporal_client

    async def execute_chain(
        self,
        graph: ExecutionGraph,
        initial_parameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Start chain execution

        Args:
            graph: ExecutionGraph from create_execution_graph
            initial_parameters: Optional parameters for first step

        Returns:
            Workflow ID for tracking

        Example:
            engine = ChainEngine(temporal_client)
            chain = load_chain("chains/my_chain.yaml")
            graph = create_execution_graph(chain)

            workflow_id = await engine.execute_chain(graph)
            print(f"Chain started: {workflow_id}")
        """
        # Lazy import to avoid circular dependency
        from temporal_gateway.workflows import ChainExecutorWorkflow, ChainExecutionRequest

        workflow_id = f"chain-{graph.chain_name}-{uuid.uuid4()}"

        await self.client.start_workflow(
            ChainExecutorWorkflow.run,
            ChainExecutionRequest(
                graph=graph,
                initial_parameters=initial_parameters
            ),
            id=workflow_id,
            task_queue="comfyui-gpu-farm"
        )

        return workflow_id

    async def get_chain_status(self, workflow_id: str) -> Dict[str, Any]:
        """
        Get current status of a running chain

        Args:
            workflow_id: Chain workflow ID

        Returns:
            Status dict with current level and step results
        """
        # Lazy import to avoid circular dependency
        from temporal_gateway.workflows import ChainExecutorWorkflow

        handle = self.client.get_workflow_handle(workflow_id)
        status = await handle.query(ChainExecutorWorkflow.get_status)
        return status

    async def get_chain_result(self, workflow_id: str) -> Dict[str, Any]:
        """
        Wait for chain to complete and get result

        Args:
            workflow_id: Chain workflow ID

        Returns:
            ChainExecutionResult as dict
        """
        handle = self.client.get_workflow_handle(workflow_id)
        result = await handle.result()
        # Result is already a dict from Temporal serialization
        return result

    async def regenerate_chain(
        self,
        chain_name: str,
        graph: ExecutionGraph,
        from_step: str,
        new_parameters: Dict[str, Any],
        use_version: Optional[int] = None
    ) -> str:
        """
        Regenerate chain from a specific step with new parameters

        This creates a new chain version that:
        - Loads cache from previous completed workflows
        - Re-executes from the specified step with new parameters
        - Continues through all descendant steps

        Args:
            chain_name: Name of the chain
            graph: ExecutionGraph for the chain
            from_step: Step ID to regenerate from
            new_parameters: Dict mapping step_id to parameters for that step
                Format: {"step_id": {"param_key": "param_value"}}
                Only steps being regenerated (from_step and descendants) will be updated
            use_version: Optional specific version to cache from (None = latest)

        Returns:
            Workflow ID for the new chain execution

        Example (RL agent updating multiple steps):
            workflow_id = await engine.regenerate_chain(
                chain_name="image-pipeline",
                graph=graph,
                from_step="edit_frame1",
                new_parameters={
                    "edit_frame1": {"111.prompt": "cyberpunk style"},
                    "edit_frame2": {"111.prompt": "neon colors"},
                    "create_video": {"6.text": "smooth transition", "60.fps": 24}
                }
            )
        """
        # Lazy import to avoid circular dependency
        from temporal_gateway.workflows import ChainExecutorWorkflow, ChainExecutionRequest

        # Get all descendants of from_step - they need to be regenerated too
        descendants = graph.get_descendants(from_step)
        descendants.add(from_step)  # Include the from_step itself

        # Build cache from database, excluding from_step and all its descendants
        cache = await self._build_cache_from_database(chain_name, exclude_step_ids=descendants)

        # Update parameters for steps that are being regenerated
        # new_parameters format: {"step_id": {"param_key": "param_value"}}
        for step_id, step_params in new_parameters.items():
            if step_id in descendants and isinstance(step_params, dict):
                graph.update_step_with_new_parameters(step_id, step_params)

        # Get next version number
        next_version = await self._get_next_chain_version(chain_name)

        # Create workflow ID with retry suffix
        workflow_id = f"chain-{chain_name}-v{next_version}-{uuid.uuid4()}"

        # Start new workflow with cache
        await self.client.start_workflow(
            ChainExecutorWorkflow.run,
            ChainExecutionRequest(
                graph=graph,
                cached_results=cache,
                retry_number=next_version  # Use version as retry number
            ),
            id=workflow_id,
            task_queue="comfyui-gpu-farm"
        )

        return workflow_id

    async def _build_cache_from_database(
        self,
        chain_name: str,
        exclude_step_ids: Optional[set] = None
    ) -> Dict[str, StepResult]:
        """
        Build cache from latest completed workflows in database

        Queries database for the most recent completed execution of each step
        in the specified chain, excluding specified steps.

        Args:
            chain_name: Name of chain to get cache from
            exclude_step_ids: Set of step IDs to exclude (from_step and its descendants)

        Returns:
            Dict mapping step_id to StepResult
        """
        cache = {}
        exclude_step_ids = exclude_step_ids or set()

        with get_session() as db:
            # Get workflows for this chain name
            stmt = (
                select(Workflow)
                .join(Chain, Workflow.chain_id == Chain.id)
                .where(
                    and_(
                        Chain.name == chain_name,
                        Workflow.status == 'completed'
                    )
                )
                .order_by(Workflow.completed_at.desc())
            )

            workflows = db.execute(stmt).scalars().all()

            # Get latest workflow per step_id, excluding specified steps
            seen_steps = set()
            for wf in workflows:
                if wf.step_id and wf.step_id not in seen_steps and wf.step_id not in exclude_step_ids:
                    # Check if artifact still exists
                    artifact_valid = True
                    artifact = None
                    if wf.latest_artifact_id:
                        artifact = db.get(Artifact, wf.latest_artifact_id)
                        if not artifact or not os.path.exists(artifact.local_path):
                            artifact_valid = False

                    if artifact_valid:
                        # Reconstruct output from artifact for template resolution
                        output = None
                        if artifact:
                            output = {
                                "image": artifact.filename  # Use original filename for ComfyUI
                            }

                        cache[wf.step_id] = StepResult(
                            step_id=wf.step_id,
                            workflow=wf.workflow_name,
                            status=wf.status,
                            artifact_id=wf.latest_artifact_id,
                            workflow_db_id=wf.id,
                            server_address=wf.server_address,
                            parameters={},
                            output=output,  # Include output for template resolution
                        )
                        seen_steps.add(wf.step_id)

        return cache

    async def _get_next_chain_version(self, chain_name: str) -> int:
        """
        Get next version number for a chain with database lock

        Uses database row-level locking to prevent concurrent version conflicts.

        Args:
            chain_name: Name of chain

        Returns:
            Next version number to use
        """
        with get_session() as db:
            # Use row-level lock to prevent concurrent version assignment
            stmt = (
                select(Chain)
                .where(Chain.name == chain_name)
                .order_by(Chain.version.desc())
                .limit(1)
                .with_for_update()  # Row-level lock
            )

            latest_chain = db.execute(stmt).scalar_one_or_none()

            if latest_chain:
                next_version = latest_chain.version + 1
            else:
                next_version = 1

            return next_version

    async def cancel_chain(self, workflow_id: str) -> None:
        """
        Cancel a running chain

        Args:
            workflow_id: Chain workflow ID
        """
        handle = self.client.get_workflow_handle(workflow_id)
        await handle.cancel()
