"""
Chain Executor Workflow

Temporal workflow that executes chain plans by orchestrating child ComfyUI workflows.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import timedelta

from temporalio import workflow as job
from temporalio.common import RetryPolicy

# Import with job.unsafe for Temporal
with job.unsafe.imports_passed_through():
    from ..chains.models import ExecutionGraph, StepResult, ChainExecutionResult
    from .comfy_executor import ComfyUIWorkflow, WorkflowExecutionRequest
    from ..activities import (
        resolve_chain_templates,
        evaluate_chain_condition,
        apply_workflow_parameters,
        select_best_server,
        transfer_artifacts_from_storage,
        create_workflow_record,
        update_chain_status_activity,
        update_workflow_status_activity,
        get_workflow_artifacts,
        publish_step_completed_activity,
        create_approval_request_activity,
        upload_local_inputs,
    )


@dataclass
class ChainExecutionRequest:
    """
    Request to execute a chain

    Attributes:
        graph: Execution graph (DAG) to execute
        initial_parameters: Optional parameters for first step
        chain_id: Database chain ID (created by gateway before starting workflow)
        chain_version: Chain version number (for logging)
        cached_results: Previously completed step results to reuse (for retry chains)
        retry_number: Retry attempt number (0 for original, 1+ for retries)
    """
    graph: ExecutionGraph
    initial_parameters: Optional[Dict[str, Any]] = None
    chain_id: Optional[str] = None  # Database chain ID for SSE events
    chain_version: int = 1  # Chain version number (for logging)
    cached_results: Optional[Dict[str, StepResult]] = None  # step_id -> StepResult
    retry_number: int = 0  # Track retry count


@job.defn
class ChainExecutorWorkflow:
    """
    Temporal workflow that executes workflow chains

    This workflow:
    1. Takes an ExecutionGraph (DAG of steps)
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
        self._chain_version: int = 1  # Chain version number
        self._workflow_ids: Dict[str, str] = {}  # Map step_id -> workflow_id

        # Input upload tracking
        self._servers_with_inputs: set = set()  # Servers that have inputs uploaded
        self._uploaded_inputs: Dict[str, str] = {}  # key -> uploaded filename

        # Approval state (per step)
        self.approval_decisions = {}  # step_id -> decision
        self.approval_decided_by = {}  # step_id -> who decided
        self.approval_parameters = {}  # step_id -> new params
        self.approval_comments = {}  # step_id -> comment

    @job.run
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

        job.logger.info(f"Starting chain execution: {graph.chain_name}")
        job.logger.info(f"Retry number: {retry_number}")
        job.logger.info(f"Cached steps: {list(cached_results.keys())}")
        job.logger.info(f"Total levels: {len(graph.get_execution_levels())}")

        try:
            # Apply cached results to graph
            for step_id, cached_result in cached_results.items():
                graph.apply_cached_result(step_id, cached_result)
                # Store in step_results for template resolution and artifact transfers
                self._step_results[step_id] = cached_result
                job.logger.info(f"Applied cache for step: {step_id}")

            # Use chain_id passed from gateway (chain record already created)
            self._chain_id = request.chain_id
            self._chain_version = request.chain_version
            job.logger.info(f"Using chain ID: {self._chain_id}, version: {self._chain_version}")

            # Store graph reference and compute uploaded input filenames
            self._graph = graph
            if graph.inputs:
                from pathlib import PurePosixPath, PureWindowsPath
                for input_key, input_def in graph.inputs.items():
                    source = input_def.get("source", "")
                    target = input_def.get("target")
                    # Get base filename, stripping any path components
                    raw_name = target if target else PurePosixPath(source).name
                    posix_name = PurePosixPath(raw_name).name
                    windows_name = PureWindowsPath(raw_name).name
                    base_name = posix_name if len(posix_name) <= len(windows_name) else windows_name
                    # Prefix with chain_id
                    self._uploaded_inputs[input_key] = f"{self._chain_id}_{base_name}"
                job.logger.info(f"Computed {len(self._uploaded_inputs)} input filename(s)")

            # Execute each level sequentially
            execution_levels = graph.get_execution_levels()
            for level_num, level_steps in enumerate(execution_levels):
                self._current_level = level_num
                self._status = f"executing_level_{level_num}"

                # Update chain status in DB
                await job.execute_activity(
                    update_chain_status_activity,
                    args=[
                        self._chain_id,
                        self._status,
                        level_num,
                        None,  # error_message
                        self._graph.chain_name,
                        self._chain_version,
                    ],
                    start_to_close_timeout=timedelta(seconds=10)
                )

                job.logger.info(f"Level {level_num}: Executing {len(level_steps)} step(s)")

                # Execute all steps in this level
                level_results = await self._execute_level(graph, level_steps)

                # Store all level results and update graph nodes
                for step_id, result in level_results.items():
                    self._step_results[step_id] = result
                    job.logger.info(f"Step {step_id}: {result.status}")

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

            # All levels complete
            self._status = "completed"

            # Update final chain status in DB
            await job.execute_activity(
                update_chain_status_activity,
                args=[
                    self._chain_id,
                    "completed",
                    None,  # current_level
                    None,  # error_message
                    self._graph.chain_name,
                    self._chain_version,
                ],
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
            job.logger.error(f"Chain execution failed: {e}")

            # Update chain status to failed in DB
            if self._chain_id:
                await job.execute_activity(
                    update_chain_status_activity,
                    args=[
                        self._chain_id,
                        "failed",
                        None,  # current_level
                        str(e),  # error_message
                        self._graph.chain_name,
                        self._chain_version,
                    ],
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
        node,
        resolved_params: dict,
        server_address: str,
    ) -> tuple[str, dict]:
        """
        Wait for approval decision from external system

        Args:
            step_id: Step identifier
            workflow_db_id: Database workflow ID
            artifact_ids: List of artifact IDs to approve
            approval_config: Approval configuration from YAML
            node: Execution node for regeneration
            resolved_params: Parameters used for workflow execution
            server_address: Server where workflow was executed

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
            job.logger.warning(f"Step {step_id}: No artifacts to approve, auto-approving")
            return "approved", {}

        # Create approval request in DB
        approval_request_data = await job.execute_activity(
            create_approval_request_activity,
            args=[
                artifact_id,
                job.info().workflow_id,  # job_id
                f"http://localhost:8001/artifacts/{artifact_id}",  # artifact_view_url
                self._chain_id,  # chain_id
                step_id,  # step_id
                job.info().run_id,  # job_run_id
                168,  # link_expiration_hours (1 week default)
                node.workflow,  # workflow_name
                server_address,  # server where workflow was executed
                resolved_params,  # parameters used for workflow execution
                approval_config,  # approval_config
                self._graph.chain_name,  # chain_name
                self._chain_version,  # chain_version
            ],
            start_to_close_timeout=timedelta(seconds=30)
        )

        job.logger.info(
            f"Step {step_id}: Approval request created, "
            f"token: {approval_request_data['token'][:16]}..."
        )

        # WAIT for approval signal with timeout
        try:
            await job.wait_condition(
                lambda: step_id in self.approval_decisions,
                timeout=timedelta(hours=timeout_hours)
            )

            # Signal received!
            decision = self.approval_decisions.get(step_id)
            if decision == "approved":
                decided_by = self.approval_decided_by.get(step_id)
                job.logger.info(f"Step {step_id}: Approved by {decided_by}")
                return "approved", {}

            elif decision == "rejected":
                decided_by = self.approval_decided_by.get(step_id)
                comment = self.approval_comments.get(step_id)
                job.logger.info(
                    f"Step {step_id}: Rejected by {decided_by}"
                    f" with comment: {comment}"
                )

                # Return decision and let caller handle retry logic
                if on_rejected == 'regenerate':
                    return "rejected", self.approval_parameters.get(step_id, {})
                elif on_rejected == 'skip':
                    job.logger.info(f"Step {step_id}: Skipping due to rejection")
                    raise Exception(f"Step {step_id} skipped due to approval rejection")
                else:  # 'stop'
                    raise Exception(f"Step {step_id} stopped due to approval rejection")

        except TimeoutError:
            # Timeout - no decision received
            job.logger.warning(
                f"Step {step_id}: Approval timeout after {timeout_hours} hours"
            )
            timeout_action = approval_config.get('timeout_action', 'auto_reject')

            if timeout_action == 'auto_approve':
                job.logger.info(f"Step {step_id}: Auto-approving due to timeout")
                return "approved", {}
            else:
                raise Exception(f"Step {step_id} timeout - no approval received")

    async def _execute_step(self, node) -> StepResult:
        """
        Execute a single step with optional approval retry loop.

        Args:
            node: StepNode from the execution graph

        Returns:
            StepResult
        """
        step_id = node.step_id
        job.logger.info(f"Executing step: {step_id}")

        try:
            # Check condition first
            if node.condition:
                should_execute = await job.execute_activity(
                    evaluate_chain_condition,
                    args=[
                        node.condition,
                        self._step_results,
                        self._graph.chain_name,
                        self._chain_version,
                        self._chain_id,
                    ],
                    start_to_close_timeout=timedelta(seconds=10)
                )
                if not should_execute:
                    job.logger.info(f"Step {step_id} skipped (condition failed)")
                    return StepResult(step_id=step_id, workflow=node.workflow, status="skipped")

            # Run with approval retry loop if needed
            return await self._run_step_with_approval(node)

        except Exception as e:
            job.logger.error(f"Step {step_id} failed: {e}")
            if step_id in self._workflow_ids:
                await job.execute_activity(
                    update_workflow_status_activity,
                    args=[
                        self._workflow_ids[step_id],
                        "failed",
                        str(e),
                        self._graph.chain_name,
                        self._chain_version,
                        self._chain_id,
                    ],
                    start_to_close_timeout=timedelta(seconds=10)
                )
            return StepResult(step_id=step_id, workflow=node.workflow, status="failed", error=str(e))

    async def _run_step_with_approval(self, node) -> StepResult:
        """
        Run step, retrying on rejection if approval is configured.

        Args:
            node: StepNode to execute

        Returns:
            StepResult after approval (or immediately if no approval needed)
        """
        step_id = node.step_id
        approval_config = node.approval_config if node.requires_approval else None
        max_retries = approval_config.get('max_retries', 0) if approval_config else 0

        override_params = None
        retry_count = 0

        while True:
            # Execute the workflow
            result, workflow_db_id, resolved_params, target_server = await self._run_workflow(
                node, override_params
            )

            # No approval required - done
            if not node.requires_approval:
                break

            # Wait for approval
            artifact_ids = await job.execute_activity(
                get_workflow_artifacts,
                args=[
                    workflow_db_id,
                    self._graph.chain_name,
                    self._chain_version,
                    self._chain_id,
                ],
                start_to_close_timeout=timedelta(seconds=10)
            )

            decision, new_params = await self._wait_for_approval(
                step_id, workflow_db_id, artifact_ids, approval_config,
                node, resolved_params, target_server
            )

            if decision == "approved":
                job.logger.info(f"Step {step_id}: Approved")
                break

            # Rejected - check retry limit
            if retry_count >= max_retries:
                raise Exception(f"Step {step_id}: max retries ({max_retries}) exhausted")

            retry_count += 1
            override_params = new_params
            job.logger.info(f"Step {step_id}: Rejected, retry {retry_count}/{max_retries + 1}")

        # Build final result
        return await self._finalize_step(node, result, workflow_db_id, resolved_params)

    async def _run_workflow(self, node, override_params: Optional[Dict] = None):
        """
        Execute a single workflow attempt.

        Args:
            node: StepNode to execute
            override_params: Optional params to override (from rejection)

        Returns:
            Tuple of (result, workflow_db_id, resolved_params, target_server)
        """
        step_id = node.step_id

        # Resolve parameters
        current_params = {**node.parameters}
        if override_params:
            current_params.update(override_params)

        resolved_params = await job.execute_activity(
            resolve_chain_templates,
            args=[
                current_params,
                self._step_results,
                self._uploaded_inputs,
                self._graph.chain_name,
                self._chain_version,
                self._chain_id,
            ],
            start_to_close_timeout=timedelta(seconds=10)
        )

        # Get workflow JSON
        workflow_json = await job.execute_activity(
            apply_workflow_parameters,
            args=[
                node.workflow,
                resolved_params,
                self._graph.chain_name,
                self._chain_version,
                self._chain_id,
            ],
            start_to_close_timeout=timedelta(seconds=30)
        )

        # Select server
        target_server = await job.execute_activity(
            select_best_server,
            args=[
                "least_loaded",
                self._graph.chain_name,
                self._chain_version,
                self._chain_id,
            ],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0
            )
        )
        job.logger.info(f"Step {step_id}: Server {target_server}")

        # Upload inputs if needed
        await self._upload_inputs_if_needed(step_id, target_server)

        # Transfer dependency artifacts
        await self._transfer_dependency_artifacts(step_id, node.dependencies, target_server)

        # Create workflow record
        workflow_db_id = await job.execute_activity(
            create_workflow_record,
            args=[
                node.workflow, target_server, "pending", self._chain_id,
                step_id, f"{job.info().workflow_id}-{step_id}", None,
                workflow_json, resolved_params,
                self._graph.chain_name, self._chain_version,
            ],
            start_to_close_timeout=timedelta(seconds=10)
        )
        self._workflow_ids[step_id] = workflow_db_id

        # Execute child workflow
        result = await job.execute_child_workflow(
            ComfyUIWorkflow.run,
            WorkflowExecutionRequest(
                workflow_definition=workflow_json,
                strategy="least_loaded",
                workflow_name=node.workflow,
                server_address=target_server,
                workflow_db_id=workflow_db_id,
                chain_id=self._chain_id,
                step_id=step_id,
                chain_name=self._graph.chain_name,
                chain_version=self._chain_version,
            ),
            id=f"{job.info().workflow_id}-{step_id}",
            task_queue="comfyui-gpu-farm",
            retry_policy=RetryPolicy(
                maximum_attempts=2,
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=60),
                backoff_coefficient=2.0
            )
        )

        # Update status
        await job.execute_activity(
            update_workflow_status_activity,
            args=[
                workflow_db_id,
                result.status,
                getattr(result, 'error', None),
                self._graph.chain_name,
                self._chain_version,
                self._chain_id,
            ],
            start_to_close_timeout=timedelta(seconds=10)
        )

        return result, workflow_db_id, resolved_params, target_server

    async def _upload_inputs_if_needed(self, step_id: str, target_server: str):
        """Upload local inputs to server if not already done."""
        if not self._graph.inputs or target_server in self._servers_with_inputs:
            return

        job.logger.info(f"Step {step_id}: Uploading inputs to {target_server}")
        await job.execute_activity(
            upload_local_inputs,
            args=[
                self._graph.inputs,
                target_server,
                str(self._chain_id),
                self._graph.chain_name,
                self._chain_version,
            ],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0
            )
        )
        self._servers_with_inputs.add(target_server)

    async def _transfer_dependency_artifacts(self, step_id: str, dependencies: List[str], target_server: str):
        """Transfer artifacts from dependency steps to target server.

        Gets artifact_id and workflow_db_id directly from step_results (works for both fresh and cached steps).
        """
        if not dependencies:
            return

        for dep_step_id in dependencies:
            dep_result = self._step_results.get(dep_step_id)
            if not dep_result:
                job.logger.warning(f"Dependency {dep_step_id} result not found")
                continue

            # Get artifact_id directly from step result
            artifact_id = (
                dep_result.get("artifact_id") if isinstance(dep_result, dict)
                else getattr(dep_result, "artifact_id", None)
            )

            if not artifact_id:
                job.logger.info(f"Dependency {dep_step_id} has no artifact to transfer")
                continue

            # Get workflow_db_id from step result (for record-keeping/traceability)
            workflow_db_id = (
                dep_result.get("workflow_db_id") if isinstance(dep_result, dict)
                else getattr(dep_result, "workflow_db_id", None)
            )

            if not workflow_db_id:
                job.logger.warning(f"Dependency {dep_step_id} has no workflow_db_id for traceability")
                continue

            job.logger.info(f"Transferring artifact {artifact_id} from {dep_step_id} (workflow: {workflow_db_id})")
            await job.execute_activity(
                transfer_artifacts_from_storage,
                args=[
                    workflow_db_id,
                    target_server,
                    [artifact_id],
                    None,
                    self._graph.chain_name,
                    self._chain_version,
                    self._chain_id,
                ],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=2),
                    maximum_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0
                )
            )

    async def _finalize_step(self, node, result, workflow_db_id: str, resolved_params: Dict) -> StepResult:
        """Build final StepResult and publish completion event."""
        step_id = node.step_id

        # Get artifact ID
        artifact_ids = await job.execute_activity(
            get_workflow_artifacts,
            args=[
                workflow_db_id,
                self._graph.chain_name,
                self._chain_version,
                self._chain_id,
            ],
            start_to_close_timeout=timedelta(seconds=10)
        )
        artifact_id = artifact_ids[0] if artifact_ids else None

        # Publish completion event with artifact ID
        if self._chain_id:
            await job.execute_activity(
                publish_step_completed_activity,
                args=[
                    self._chain_id,
                    step_id,
                    self._graph.chain_name,
                    self._chain_version,
                    artifact_id,  # Include artifact ID for frontend preview
                ],
                start_to_close_timeout=timedelta(seconds=10)
            )

        return StepResult(
            step_id=step_id,
            workflow=node.workflow,
            status=result.status,
            output=result.output,
            parameters=resolved_params,
            server_address=result.server_address,
            workflow_db_id=workflow_db_id,
            artifact_id=artifact_id,
        )

    async def _execute_level(
        self,
        graph: 'ExecutionGraph',
        level_steps: List[str]
    ) -> Dict[str, StepResult]:
        """
        Execute all steps in a level in parallel.

        Args:
            graph: Execution graph
            level_steps: List of step IDs in this level

        Returns:
            Dict mapping step_id to StepResult
        """
        import asyncio

        tasks = {}
        results = {}

        for step_id in level_steps:
            node = graph.get_node(step_id)

            # Check if this step is already cached
            if node.status == "completed":
                job.logger.info(f"Step {step_id}: Using cached result")
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
                    job.logger.warning(
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
                    job.logger.error(f"Step {step_id} raised exception: {task_result}")
                    results[step_id] = StepResult(
                        step_id=step_id,
                        workflow=graph.get_node(step_id).workflow,
                        status="failed",
                        error=str(task_result)
                    )
                else:
                    results[step_id] = task_result

        return results

    @job.signal
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

        job.logger.info(f"Received approval decision for step {step_id}: {decision} by {decided_by}")

        # Store per-step approval state
        self.approval_decisions[step_id] = decision
        self.approval_decided_by[step_id] = decided_by
        self.approval_parameters[step_id] = parameters or {}
        self.approval_comments[step_id] = comment

    @job.query
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
