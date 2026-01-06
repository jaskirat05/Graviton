"""
Chain Executor Workflow

Temporal workflow that executes chain plans by orchestrating child ComfyUI workflows.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import with workflow.unsafe for Temporal
with workflow.unsafe.imports_passed_through():
    from ...chains.models import ExecutionGraph, StepResult, ChainExecutionResult
    from ..comfy_workflow import ComfyUIWorkflow, WorkflowExecutionRequest
    from ...activities import (
        resolve_chain_templates,
        evaluate_chain_condition,
        apply_workflow_parameters,
        select_best_server,
        transfer_artifacts_from_storage,
        create_chain_record,
        create_workflow_record,
        update_chain_status_activity,
        update_workflow_status_activity,
        get_workflow_artifacts,
        create_approval_request_activity,
    )


@dataclass
class ChainExecutionRequest:
    """
    Request to execute a chain

    Attributes:
        graph: Execution graph (DAG) to execute
        initial_parameters: Optional parameters for first step
        cached_results: Previously completed step results to reuse (for retry chains)
        retry_number: Retry attempt number (0 for original, 1+ for retries)
    """
    graph: ExecutionGraph
    initial_parameters: Optional[Dict[str, Any]] = None
    cached_results: Optional[Dict[str, StepResult]] = None  # step_id -> StepResult
    retry_number: int = 0  # Track retry count


@workflow.defn
class ChainExecutorWorkflow:
    """
    Temporal workflow that executes workflow chains

    This workflow:
    1. Takes an ExecutionPlan from ChainInterpreter
    2. Executes steps level by level (sequential levels, parallel within level)
    3. Resolves Jinja2 templates using previous step results
    4. Evaluates conditions to skip steps
    5. Executes each step as a child ComfyUIWorkflow
    6. Returns ChainExecutionResult with all step results
    """

    def __init__(self):
        self._status = "initializing"
        self._current_level = 0
        self._step_results: Dict[str, StepResult] = {}
        self._chain_id: Optional[str] = None  # Database chain ID
        self._workflow_ids: Dict[str, str] = {}  # Map step_id -> workflow_id

        # Approval state (per step)
        self.approval_decisions = {}  # step_id -> decision
        self.approval_decided_by = {}  # step_id -> who decided
        self.approval_parameters = {}  # step_id -> new params
        self.approval_comments = {}  # step_id -> comment

    @workflow.run
    async def run(self, request: ChainExecutionRequest) -> ChainExecutionResult:
        """
        Execute chain with cache support and regeneration

        Args:
            request: Chain execution request with ExecutionGraph and optional cache

        Returns:
            ChainExecutionResult with all step results
        """
        graph = request.graph
        cached_results = request.cached_results or {}
        retry_number = request.retry_number

        workflow.logger.info(f"Starting chain execution: {graph.chain_name}")
        workflow.logger.info(f"Retry number: {retry_number}")
        workflow.logger.info(f"Cached steps: {list(cached_results.keys())}")
        workflow.logger.info(f"Total levels: {len(graph.get_execution_levels())}")

        try:
            # Apply cached results to graph
            for step_id, cached_result in cached_results.items():
                graph.apply_cached_result(step_id, cached_result)
                # Also store in step_results for template resolution
                self._step_results[step_id] = cached_result
                workflow.logger.info(f"Applied cache for step: {step_id}")

            # Create chain record in database
            self._chain_id = await workflow.execute_activity(
                create_chain_record,
                args=[
                    graph.chain_name,
                    workflow.info().workflow_id,
                    workflow.info().run_id,
                    None,  # chain_definition - can add later
                    None,  # description
                ],
                start_to_close_timeout=timedelta(seconds=10)
            )
            workflow.logger.info(f"Created chain record: {self._chain_id}")

            # Execute each level sequentially
            execution_levels = graph.get_execution_levels()
            for level_num, level_steps in enumerate(execution_levels):
                self._current_level = level_num
                self._status = f"executing_level_{level_num}"

                # Update chain status in DB
                await workflow.execute_activity(
                    update_chain_status_activity,
                    args=[self._chain_id, self._status, level_num],
                    start_to_close_timeout=timedelta(seconds=10)
                )

                workflow.logger.info(f"Level {level_num}: Executing {len(level_steps)} step(s)")

                # Execute level and check for rejection
                level_results, rejected_step = await self._execute_level(graph, level_steps)

                # Store all level results and update graph nodes
                for step_id, result in level_results.items():
                    self._step_results[step_id] = result
                    workflow.logger.info(f"Step {step_id}: {result.status}")

                    # Update graph node status so dependencies work
                    node = graph.get_node(step_id)
                    if node:
                        if result.status == "completed":
                            node.mark_completed(
                                artifact_id=result.artifact_id,
                                workflow_db_id=result.workflow_db_id
                            )
                        elif result.status == "failed":
                            node.mark_failed(result.error or "Unknown error")
                        elif result.status.startswith("skipped"):
                            node.status = result.status
                            node.skipped_reason = result.skipped_reason

                # Check if any step was rejected
                if rejected_step:
                    workflow.logger.warning(f"Step {rejected_step} was rejected")

                    # Build cache from all completed steps (including this level)
                    cache_for_retry = await self._build_cache_for_retry(graph)

                    # Spawn retry chain
                    await self._spawn_retry_chain(
                        graph=graph,
                        rejected_step=rejected_step,
                        cache=cache_for_retry,
                        retry_number=retry_number + 1
                    )

                    # Mark current chain as cancelled/partial
                    self._status = "partial"
                    await workflow.execute_activity(
                        update_chain_status_activity,
                        args=[self._chain_id, "partial", None, f"Step {rejected_step} rejected"],
                        start_to_close_timeout=timedelta(seconds=10)
                    )

                    return ChainExecutionResult(
                        chain_name=graph.chain_name,
                        chain_db_id=self._chain_id,
                        status="partial",
                        step_results=self._step_results,
                        error=f"Step {rejected_step} was rejected, retry chain spawned"
                    )

            # All levels complete
            self._status = "completed"

            # Update final chain status in DB
            await workflow.execute_activity(
                update_chain_status_activity,
                args=[self._chain_id, "completed"],
                start_to_close_timeout=timedelta(seconds=10)
            )

            return ChainExecutionResult(
                chain_name=graph.chain_name,
                chain_db_id=self._chain_id,
                status="completed",
                step_results=self._step_results
            )

        except Exception as e:
            self._status = "failed"
            workflow.logger.error(f"Chain execution failed: {e}")

            # Update chain status to failed in DB
            if self._chain_id:
                await workflow.execute_activity(
                    update_chain_status_activity,
                    args=[self._chain_id, "failed", None, str(e)],
                    start_to_close_timeout=timedelta(seconds=10)
                )

            return ChainExecutionResult(
                chain_name=graph.chain_name,
                chain_db_id=self._chain_id,
                status="failed",
                step_results=self._step_results,
                error=str(e)
            )

    async def _wait_for_approval(
        self,
        step_id: str,
        workflow_db_id: str,
        artifact_ids: list,
        approval_config: dict,
        node
    ) -> tuple[str, dict]:
        """
        Wait for approval decision from external system

        Args:
            step_id: Step identifier
            workflow_db_id: Database workflow ID
            artifact_ids: List of artifact IDs to approve
            approval_config: Approval configuration from YAML
            node: Execution node for regeneration

        Returns:
            Tuple of (decision, parameters) - parameters will be new params if rejected
        """
        timeout_hours = approval_config.get('timeout_hours', 24)
        on_rejected = approval_config.get('on_rejected', 'stop')

        # Reset approval state for this step
        if step_id in self.approval_decisions:
            del self.approval_decisions[step_id]
        if step_id in self.approval_parameters:
            del self.approval_parameters[step_id]

        # Create approval request for the artifact
        # Assuming first artifact for now (can be extended for multiple)
        artifact_id = artifact_ids[0] if artifact_ids else None

        if not artifact_id:
            workflow.logger.warning(f"Step {step_id}: No artifacts to approve, auto-approving")
            return "approved", {}

        # Create approval request in DB
        approval_request_data = await workflow.execute_activity(
            create_approval_request_activity,
            args=[
                artifact_id,
                workflow.info().workflow_id,  # Parent workflow ID (same for all steps)
                f"http://localhost:8001/artifacts/{artifact_id}",  # artifact_view_url
                self._chain_id,  # chain_id
                step_id,  # step_id
                workflow.info().run_id,  # temporal_run_id
                168,  # link_expiration_hours (1 week default)
                node.workflow,  # workflow_name
                None,  # server (can add if needed)
                {},  # parameters (current parameters from node)
                approval_config,  # approval_config
            ],
            start_to_close_timeout=timedelta(seconds=30)
        )

        workflow.logger.info(
            f"Step {step_id}: Approval request created, "
            f"token: {approval_request_data['token'][:16]}..."
        )

        # WAIT for approval signal with timeout
        try:
            await workflow.wait_condition(
                lambda: step_id in self.approval_decisions,
                timeout=timedelta(hours=timeout_hours)
            )

            # Signal received!
            decision = self.approval_decisions.get(step_id)
            if decision == "approved":
                decided_by = self.approval_decided_by.get(step_id)
                workflow.logger.info(f"Step {step_id}: Approved by {decided_by}")
                return "approved", {}

            elif decision == "rejected":
                decided_by = self.approval_decided_by.get(step_id)
                comment = self.approval_comments.get(step_id)
                workflow.logger.info(
                    f"Step {step_id}: Rejected by {decided_by}"
                    f" with comment: {comment}"
                )

                # Return decision and let caller handle retry logic
                if on_rejected == 'regenerate':
                    return "rejected", self.approval_parameters.get(step_id, {})
                elif on_rejected == 'skip':
                    workflow.logger.info(f"Step {step_id}: Skipping due to rejection")
                    raise Exception(f"Step {step_id} skipped due to approval rejection")
                else:  # 'stop'
                    raise Exception(f"Step {step_id} stopped due to approval rejection")

        except TimeoutError:
            # Timeout - no decision received
            workflow.logger.warning(
                f"Step {step_id}: Approval timeout after {timeout_hours} hours"
            )
            timeout_action = approval_config.get('timeout_action', 'auto_reject')

            if timeout_action == 'auto_approve':
                workflow.logger.info(f"Step {step_id}: Auto-approving due to timeout")
                return "approved", {}
            else:
                raise Exception(f"Step {step_id} timeout - no approval received")

    async def _execute_step(self, node) -> StepResult:
        """
        Execute a single step as a child workflow with approval support

        Args:
            node: ExecutionNode from the plan

        Returns:
            StepResult
        """
        step_id = node.step_id
        workflow.logger.info(f"Executing step: {step_id}")

        try:
            # 1. Evaluate condition (if any) using activity
            if node.condition:
                should_execute = await workflow.execute_activity(
                    evaluate_chain_condition,
                    args=[node.condition, self._step_results],
                    start_to_close_timeout=timedelta(seconds=10)
                )

                if not should_execute:
                    workflow.logger.info(f"Step {step_id} skipped (condition failed)")
                    return StepResult(
                        step_id=step_id,
                        workflow=node.workflow,
                        status="skipped"
                    )

            # Check if step requires approval
            requires_approval = node.requires_approval
            approval_config = node.approval_config if requires_approval else None
            max_retries = approval_config.get('max_retries', 0) if approval_config else 0

            # Regeneration loop for approval rejections
            regeneration_params = None
            retry_count = 0
            final_decision = None  # Track final approval decision
            while True:
                # 2. Resolve templates in parameters using activity
                # Merge with regeneration params if this is a retry
                current_params = {**node.parameters}
                if regeneration_params:
                    current_params.update(regeneration_params)

                resolved_params = await workflow.execute_activity(
                    resolve_chain_templates,
                    args=[current_params, self._step_results],
                    start_to_close_timeout=timedelta(seconds=10)
                )

                workflow.logger.info(f"Step {step_id}: Resolved parameters")

                # 3. Get workflow JSON and apply parameters using activity
                workflow_json = await workflow.execute_activity(
                    apply_workflow_parameters,
                    args=[node.workflow, resolved_params],
                    start_to_close_timeout=timedelta(seconds=30)
                )

                # 4. Pre-select target server for this step
                target_server = await workflow.execute_activity(
                    select_best_server,
                    "least_loaded",
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=10),
                        backoff_coefficient=2.0
                    )
                )
                workflow.logger.info(f"Step {step_id}: Selected target server: {target_server}")

                # 5. Transfer artifacts from dependency steps to target server
                if node.dependencies:
                    workflow.logger.info(f"Step {step_id}: Processing {len(node.dependencies)} dependency step(s)")

                    for dep_step_id in node.dependencies:
                        # Get dependency workflow ID from our tracking
                        dep_workflow_id = self._workflow_ids.get(dep_step_id)

                        if not dep_workflow_id:
                            workflow.logger.warning(f"Dependency {dep_step_id} workflow ID not found - skipping transfer")
                            continue

                        # Get artifact IDs for the dependency workflow
                        artifact_ids = await workflow.execute_activity(
                            get_workflow_artifacts,
                            args=[dep_workflow_id],
                            start_to_close_timeout=timedelta(seconds=10)
                        )

                        if not artifact_ids:
                            workflow.logger.info(f"Dependency {dep_step_id} has no artifacts - skipping transfer")
                            continue

                        workflow.logger.info(f"Transferring {len(artifact_ids)} artifact(s) from {dep_step_id} to {target_server}")

                        # Transfer artifacts from local storage to target server
                        await workflow.execute_activity(
                            transfer_artifacts_from_storage,
                            args=[dep_workflow_id, target_server, artifact_ids, None],
                            start_to_close_timeout=timedelta(minutes=5),
                            retry_policy=RetryPolicy(
                                maximum_attempts=3,
                                initial_interval=timedelta(seconds=2),
                                maximum_interval=timedelta(seconds=10),
                                backoff_coefficient=2.0
                            )
                        )

                # 6. Create workflow record in database (before execution)
                # Note: We don't have prompt_id yet, will use placeholder
                workflow_db_id = await workflow.execute_activity(
                    create_workflow_record,
                    args=[
                        node.workflow,                          # workflow_name
                        target_server,                          # server_address
                        "pending",                              # prompt_id (placeholder)
                        self._chain_id,                         # chain_id
                        step_id,                                # step_id
                        f"{workflow.info().workflow_id}-{step_id}",  # temporal_workflow_id
                        None,                                   # temporal_run_id
                        workflow_json,                          # workflow_definition
                        resolved_params,                        # parameters
                    ],
                    start_to_close_timeout=timedelta(seconds=10)
                )

                # Store workflow ID for this step
                self._workflow_ids[step_id] = workflow_db_id
                workflow.logger.info(f"Step {step_id}: Created workflow record {workflow_db_id}")

                # 7. Execute as child workflow with pre-selected server
                child_workflow_id = f"{workflow.info().workflow_id}-{step_id}"

                result = await workflow.execute_child_workflow(
                    ComfyUIWorkflow.run,
                    WorkflowExecutionRequest(
                        workflow_definition=workflow_json,
                        strategy="least_loaded",
                        workflow_name=node.workflow,
                        server_address=target_server,  # Pass pre-selected server
                        workflow_db_id=workflow_db_id,  # Pass DB workflow ID for artifact linking
                    ),
                    id=child_workflow_id,
                    task_queue="comfyui-gpu-farm",
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(seconds=10),
                        maximum_interval=timedelta(seconds=60),
                        backoff_coefficient=2.0
                    )
                )

                # 8. Update workflow status to completed in DB
                await workflow.execute_activity(
                    update_workflow_status_activity,
                    args=[workflow_db_id, result.status, result.error if hasattr(result, 'error') else None],
                    start_to_close_timeout=timedelta(seconds=10)
                )

                # 9. Wait for approval if required
                if requires_approval:
                    workflow.logger.info(f"Step {step_id}: Approval required, fetching artifacts...")

                    # Get artifact IDs for approval
                    artifact_ids = await workflow.execute_activity(
                        get_workflow_artifacts,
                        args=[workflow_db_id],
                        start_to_close_timeout=timedelta(seconds=10)
                    )

                    # Wait for approval decision
                    decision, new_params = await self._wait_for_approval(
                        step_id,
                        workflow_db_id,
                        artifact_ids,
                        approval_config,
                        node
                    )

                    if decision == "approved":
                        workflow.logger.info(f"Step {step_id}: Approved, continuing...")
                        # Break out of regeneration loop
                        break
                    elif decision == "rejected":
                        # Check if we've exhausted retries
                        if retry_count >= max_retries:
                            raise Exception(
                                f"Step {step_id} stopped: maximum retries ({max_retries}) exhausted"
                            )

                        # Increment retry count and regenerate
                        retry_count += 1
                        regeneration_params = new_params
                        workflow.logger.info(
                            f"Step {step_id}: Rejected, regenerating with new parameters "
                            f"(attempt {retry_count + 1}/{max_retries + 1})..."
                        )
                        continue
                else:
                    # No approval required, break out of loop
                    break

            # 10. Get artifact IDs for the result
            artifact_ids = await workflow.execute_activity(
                get_workflow_artifacts,
                args=[workflow_db_id],
                start_to_close_timeout=timedelta(seconds=10)
            )
            artifact_id = artifact_ids[0] if artifact_ids else None

            # 11. Return step result with workflow ID and artifact ID
            return StepResult(
                step_id=step_id,
                workflow=node.workflow,
                status=result.status,
                output=result.output,
                parameters=resolved_params,
                server_address=result.server_address,
                workflow_db_id=workflow_db_id,
                artifact_id=artifact_id,  # For graph node updates
            )

        except Exception as e:
            workflow.logger.error(f"Step {step_id} failed: {e}")

            # Update workflow status to failed if we created the record
            if step_id in self._workflow_ids:
                await workflow.execute_activity(
                    update_workflow_status_activity,
                    args=[self._workflow_ids[step_id], "failed", str(e)],
                    start_to_close_timeout=timedelta(seconds=10)
                )

            return StepResult(
                step_id=step_id,
                workflow=node.workflow,
                status="failed",
                error=str(e)
            )

    async def _execute_level(
        self,
        graph: 'ExecutionGraph',
        level_steps: List[str]
    ) -> tuple[Dict[str, StepResult], Optional[str]]:
        """
        Execute all steps in a level and wait for completion

        This implements the wait-for-completion pattern:
        - Start all steps in parallel
        - Wait for ALL to complete (don't cancel on rejection)
        - Return all results + any rejected step

        Args:
            graph: Execution graph
            level_steps: List of step IDs in this level

        Returns:
            Tuple of (results dict, rejected_step_id or None)
        """
        import asyncio

        # Track tasks
        tasks = {}
        results = {}
        rejected_step = None

        for step_id in level_steps:
            node = graph.get_node(step_id)

            # Check if this step is already cached
            if node.status == "completed":
                workflow.logger.info(f"Step {step_id}: Using cached result")
                # Use existing cached result from self._step_results (preserves output for template resolution)
                if step_id in self._step_results:
                    results[step_id] = self._step_results[step_id]
                continue

            # Check if dependencies are satisfied
            deps_satisfied = True
            for dep_id in node.dependencies:
                dep_node = graph.get_node(dep_id)
                if not dep_node or dep_node.status != "completed":
                    # Dependency not satisfied - skip this step
                    workflow.logger.warning(
                        f"Step {step_id}: Dependency {dep_id} not satisfied, skipping"
                    )
                    node.mark_skipped_dependency(dep_id)
                    result = StepResult(
                        step_id=step_id,
                        workflow=node.workflow,
                        status="skipped_dependency",
                        skipped_reason=f"Dependency {dep_id} not satisfied"
                    )
                    results[step_id] = result
                    deps_satisfied = False
                    break

            if not deps_satisfied:
                continue

            # Execute step as async task
            task = self._execute_step(node)
            tasks[step_id] = task

        # Wait for ALL tasks to complete
        if tasks:
            task_results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            for step_id, task_result in zip(tasks.keys(), task_results):
                if isinstance(task_result, Exception):
                    workflow.logger.error(f"Step {step_id} raised exception: {task_result}")
                    results[step_id] = StepResult(
                        step_id=step_id,
                        workflow=graph.get_node(step_id).workflow,
                        status="failed",
                        error=str(task_result)
                    )
                else:
                    results[step_id] = task_result

                    # Check if this step was rejected
                    if task_result.approval_decision == "rejected":
                        rejected_step = step_id
                        workflow.logger.warning(f"Step {step_id} was rejected")

        return results, rejected_step

    async def _build_cache_for_retry(self, graph: 'ExecutionGraph') -> Dict[str, Dict]:
        """
        Build cache from current graph's completed steps

        Called when rejection happens - extracts all successfully completed
        steps from the CURRENT execution to preserve their work.

        Args:
            graph: Current execution graph

        Returns:
            Cache dict mapping step_id to step data
        """
        cache = {}

        for step_id, node in graph.nodes.items():
            if node.status == "completed" and node.artifact_id:
                cache[step_id] = {
                    "step_id": step_id,
                    "workflow": node.workflow,
                    "status": "completed",
                    "artifact_id": node.artifact_id,
                    "workflow_db_id": node.workflow_db_id,
                    "server_address": node.server_address,
                    "parameters": node.parameters,
                }
                workflow.logger.info(f"Cached step {step_id} for retry (artifact: {node.artifact_id})")

        workflow.logger.info(f"Built cache with {len(cache)} completed steps")
        return cache

    async def _spawn_retry_chain(
        self,
        graph: 'ExecutionGraph',
        rejected_step: str,
        cache: Dict[str, Dict],
        retry_number: int
    ):
        """
        Spawn a new chain execution with cache after rejection

        This starts a completely new chain workflow with:
        - Same graph structure
        - Cached results from successful steps
        - Updated parameters for rejected step

        Args:
            graph: Original execution graph
            rejected_step: Step that was rejected
            cache: Cache dict of completed steps
            retry_number: Retry attempt number
        """
        from . import ChainExecutorWorkflow

        # Update rejected step with new parameters (if provided)
        if rejected_step in self.approval_parameters:
            graph.update_step_with_new_parameters(
                rejected_step,
                self.approval_parameters[rejected_step]
            )

        # Create retry chain request
        retry_request = ChainExecutionRequest(
            graph=graph,
            cached_results=cache,
            retry_number=retry_number
        )

        # Start retry chain as child workflow
        retry_workflow_id = f"{workflow.info().workflow_id}-retry-{retry_number}"

        workflow.logger.info(
            f"Spawning retry chain {retry_workflow_id} "
            f"with {len(cache)} cached steps"
        )

        # Execute as child workflow (fire and forget - don't wait)
        await workflow.start_child_workflow(
            ChainExecutorWorkflow.run,
            args=[retry_request],
            id=retry_workflow_id,
            task_queue="comfyui-gpu-farm"
        )

        workflow.logger.info(f"Retry chain {retry_workflow_id} started")

    @workflow.signal
    async def approval_decision_signal(self, signal_data: dict):
        """
        Signal handler for approval decisions

        Called by external approval system when user approves/rejects

        Args:
            signal_data: Dict containing:
                - decision: "approved" or "rejected"
                - decided_by: Who made the decision
                - parameters: New parameters (if rejected)
                - comment: Optional comment
        """
        step_id = signal_data.get("step_id")
        decision = signal_data.get("decision")
        decided_by = signal_data.get("decided_by")
        parameters = signal_data.get("parameters", {})
        comment = signal_data.get("comment")

        workflow.logger.info(f"Received approval decision for step {step_id}: {decision} by {decided_by}")

        # Store per-step approval state
        self.approval_decisions[step_id] = decision
        self.approval_decided_by[step_id] = decided_by
        self.approval_parameters[step_id] = parameters or {}
        self.approval_comments[step_id] = comment

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """
        Query current chain execution status

        Returns:
            Status dict with current level and step results
        """
        return {
            "status": self._status,
            "current_level": self._current_level,
            "completed_steps": len(self._step_results),
            "step_statuses": {
                step_id: result.status
                for step_id, result in self._step_results.items()
            }
        }
