"""
Chain Engine

Service layer for executing workflow chains using Temporal.
"""

import asyncio
import uuid
from typing import Dict, Any, Optional
from sqlalchemy import select

from temporalio.client import Client

from .models import ExecutionGraph, StepResult, ChainExecutionResult
from .hashing import calculate_definition_hash
from ..database.session import get_session
from ..database.models import Chain
from ..services.cache import build_cache_from_database
from ..observability.chain_logger import ChainLogger


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
        chain_definition: Optional[Dict[str, Any]] = None,
        initial_parameters: Optional[Dict[str, Any]] = None,
        level_wait_seconds: int = 0,
    ) -> Dict[str, str]:
        """
        Start chain execution

        Args:
            graph: ExecutionGraph from create_execution_graph
            chain_definition: Original chain definition dict (for caching)
            initial_parameters: Optional parameters for first step

        Returns:
            Dict with:
                - chain_id: Database chain ID (for SSE subscription)
                - job_id: Temporal job ID (for status/result queries)
                - definition_hash: Hash of chain definition (for cache lookup)

        Example:
            engine = ChainEngine(temporal_client)
            chain = load_chain("chains/my_chain.yaml")
            graph = create_execution_graph(chain)

            result = await engine.execute_chain(graph, chain_definition=chain_def)
            print(f"Chain started: {result['chain_id']}, hash: {result['definition_hash']}")
        """
        # Lazy import to avoid circular dependency
        from core.executors import ChainExecutorWorkflow, ChainExecutionRequest
        from ..database.crud.chain import create_chain

        job_id = f"chain-{graph.chain_name}-{uuid.uuid4()}"

        # Calculate definition hash for cache lookup
        definition_hash = None
        if chain_definition:
            definition_hash = calculate_definition_hash(chain_definition)

        # Create chain record in database BEFORE starting workflow
        # This gives us a stable chain_id for SSE subscriptions
        with get_session() as session:
            chain_record = create_chain(
                session=session,
                name=graph.chain_name,
                job_id=job_id,
                job_run_id=None,  # Will be updated when workflow starts
                status="starting",
                chain_definition=chain_definition,
                definition_hash=definition_hash,
            )
            chain_id = chain_record.id
            chain_version = chain_record.version

        # Create chain logger and save definition (gateway responsibility)
        chain_logger = ChainLogger.create(
            chain_name=graph.chain_name,
            version=chain_version,
            chain_id=chain_id,
        )
        if chain_definition:
            chain_logger.save_chain_definition(chain_definition)
        chain_logger.gateway.info(f"Chain execution started: {job_id}")

        # Start Temporal workflow with the chain_id
        await self.client.start_workflow(
            ChainExecutorWorkflow.run,
            ChainExecutionRequest(
                graph=graph,
                initial_parameters=initial_parameters,
                chain_id=chain_id,
                chain_version=chain_version,
                level_wait_seconds=level_wait_seconds,
            ),
            id=job_id,
            task_queue="comfyui-gpu-farm"
        )

        return {
            "chain_id": chain_id,
            "job_id": job_id,
            "definition_hash": definition_hash,
        }

    async def get_chain_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get current status of a running chain

        Args:
            job_id: Job ID (Temporal workflow ID)

        Returns:
            Status dict with current level and step results
        """
        # Lazy import to avoid circular dependency
        from core.executors import ChainExecutorWorkflow

        handle = self.client.get_workflow_handle(job_id)
        status = await handle.query(ChainExecutorWorkflow.get_status)
        return status

    async def get_chain_result(self, job_id: str) -> Dict[str, Any]:
        """
        Wait for chain to complete and get result

        Args:
            job_id: Job ID (Temporal workflow ID)

        Returns:
            ChainExecutionResult as dict
        """
        handle = self.client.get_workflow_handle(job_id)
        result = await handle.result()
        # Result is already a dict from Temporal serialization
        return result

    async def regenerate_chain(
        self,
        chain_name: str,
        graph: ExecutionGraph,
        from_step: str,
        new_parameters: Dict[str, Any],
        chain_definition: Optional[Dict[str, Any]] = None,
        definition_hash: Optional[str] = None,
        level_wait_seconds: int = 0,
    ) -> Dict[str, str]:
        """
        Regenerate chain from a specific step with new parameters

        Args:
            chain_name: Name of the chain
            graph: ExecutionGraph for the chain
            from_step: Step ID to regenerate from
            new_parameters: Dict mapping step_id to parameters
            chain_definition: Original chain definition (for storage)
            definition_hash: Hash of chain definition

        Returns:
            Dict with chain_id and job_id
        """
        from core.executors import ChainExecutorWorkflow, ChainExecutionRequest
        from ..database.crud.chain import create_chain

        # Get all descendants of from_step - they need to be regenerated too
        descendants = graph.get_descendants(from_step)
        descendants.add(from_step)

        # Build cache from database, excluding from_step and descendants
        cache = build_cache_from_database(chain_name, exclude_step_ids=descendants)

        # Update parameters for steps being regenerated
        for step_id, step_params in new_parameters.items():
            if step_id in descendants and isinstance(step_params, dict):
                graph.update_step_with_new_parameters(step_id, step_params)

        job_id = f"chain-{chain_name}-regen-{uuid.uuid4()}"

        # Create chain record in database for SSE events
        with get_session() as session:
            chain_record = create_chain(
                session=session,
                name=chain_name,
                job_id=job_id,
                status="starting",
                chain_definition=chain_definition,
                definition_hash=definition_hash,
                regenerated_from_step_id=from_step,
            )
            chain_id = chain_record.id
            chain_version = chain_record.version

        # Create chain logger and save definition + cached steps (gateway responsibility)
        chain_logger = ChainLogger.create(
            chain_name=chain_name,
            version=chain_version,
            chain_id=chain_id,
        )
        if chain_definition:
            chain_logger.save_chain_definition(chain_definition)
        if cache:
            # Convert StepResult objects to dicts for JSON serialization
            cached_steps_dict = {}
            for step_id, result in cache.items():
                if hasattr(result, '__dict__'):
                    cached_steps_dict[step_id] = {
                        k: v for k, v in result.__dict__.items()
                        if not k.startswith('_')
                    }
                else:
                    cached_steps_dict[step_id] = result
            chain_logger.save_cached_steps(cached_steps_dict)
        chain_logger.gateway.info(f"Chain regeneration started from step: {from_step}")
        chain_logger.gateway.info(f"Regenerating steps: {list(descendants)}")

        # Start workflow with chain_id for SSE
        await self.client.start_workflow(
            ChainExecutorWorkflow.run,
            ChainExecutionRequest(
                graph=graph,
                cached_results=cache,
                chain_id=chain_id,
                chain_version=chain_version,
                level_wait_seconds=level_wait_seconds,
            ),
            id=job_id,
            task_queue="comfyui-gpu-farm"
        )

        return {
            "chain_id": chain_id,
            "job_id": job_id,
        }

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

    async def cancel_chain(self, job_id: str) -> None:
        """
        Cancel a running chain

        Args:
            job_id: Job ID (Temporal workflow ID)
        """
        handle = self.client.get_workflow_handle(job_id)
        await handle.cancel()

    async def abort_chain(self, job_id: str, grace_seconds: float = 5.0) -> str:
        """
        Abort a running chain with escalation.

        First requests cooperative cancellation. If the workflow does not stop
        within grace_seconds, force-terminate it.

        Args:
            job_id: Job ID (Temporal workflow ID)
            grace_seconds: Seconds to wait before force termination

        Returns:
            "cancelled" if cooperative cancel completed, "terminated" if force-killed
        """
        handle = self.client.get_workflow_handle(job_id)
        await handle.cancel()

        try:
            await asyncio.wait_for(handle.result(), timeout=grace_seconds)
            return "cancelled"
        except asyncio.TimeoutError:
            await handle.terminate(
                reason=f"Abort-all escalation after {grace_seconds:.1f}s cancel grace period"
            )
            return "terminated"
        except Exception:
            # Workflow finished (including cancellation/failure) while waiting.
            return "cancelled"
