"""
Execution Result Models

Models for tracking execution results and outcomes.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class StepResult:
    """
    Result of executing a single step

    This is a simplified snapshot of execution outcome, extracted from StepNode
    after execution completes.

    Attributes:
        step_id: Step identifier
        workflow: Workflow name that was executed
        status: Execution status (completed, failed, skipped_*, timeout, rejected)
        output: Step output data (for template resolution in downstream steps)
        parameters: Resolved parameters used for execution
        artifact_id: Database artifact UUID (string) produced by this step (single output)
        workflow_db_id: Database workflow UUID (string) for this execution
        server_address: Server where step executed
        error: Error message if failed
        skipped_reason: Reason if skipped
        execution_time: Time taken in seconds
        approval_decision: Approval decision if step required approval
    """
    step_id: str
    workflow: str
    status: str
    output: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    artifact_id: Optional[str] = None  # UUID string from database
    workflow_db_id: Optional[str] = None  # UUID string from database
    server_address: Optional[str] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    execution_time: Optional[float] = None
    approval_decision: Optional[str] = None  # "approved", "rejected", None

    def is_successful(self) -> bool:
        """Check if step completed successfully"""
        return self.status == "completed"

    def is_failed(self) -> bool:
        """Check if step failed"""
        return self.status == "failed"

    def is_skipped(self) -> bool:
        """Check if step was skipped"""
        return self.status.startswith("skipped_")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "step_id": self.step_id,
            "workflow": self.workflow,
            "status": self.status,
            "output": self.output,
            "parameters": self.parameters,
            "artifact_id": self.artifact_id,
            "workflow_db_id": self.workflow_db_id,
            "server_address": self.server_address,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
            "execution_time": self.execution_time,
            "approval_decision": self.approval_decision,
        }


@dataclass
class ChainExecutionResult:
    """
    Result of executing an entire chain

    Attributes:
        chain_name: Name of the chain
        chain_db_id: Database chain ID
        status: Overall status (completed, failed, partial, timeout)
        step_results: Dict mapping step_id to StepResult
        total_execution_time: Total time in seconds
        error: Error message if chain failed
        child_chains: List of child chain IDs spawned from this chain
    """
    chain_name: str
    chain_db_id: Optional[int] = None
    status: str = "pending"  # pending, executing, completed, failed, partial, timeout
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    total_execution_time: Optional[float] = None
    error: Optional[str] = None
    child_chains: List[int] = field(default_factory=list)  # List of child chain DB IDs

    def add_step_result(self, result: StepResult):
        """Add a step result to the chain result"""
        self.step_results[result.step_id] = result

    def get_step_result(self, step_id: str) -> Optional[StepResult]:
        """Get result for a specific step"""
        return self.step_results.get(step_id)

    def get_successful_steps(self) -> List[str]:
        """Get list of step IDs that completed successfully"""
        return [
            step_id for step_id, result in self.step_results.items()
            if result.is_successful()
        ]

    def get_failed_steps(self) -> List[str]:
        """Get list of step IDs that failed"""
        return [
            step_id for step_id, result in self.step_results.items()
            if result.is_failed()
        ]

    def get_skipped_steps(self) -> List[str]:
        """Get list of step IDs that were skipped"""
        return [
            step_id for step_id, result in self.step_results.items()
            if result.is_skipped()
        ]

    def calculate_final_status(self):
        """Calculate overall chain status based on step results"""
        if not self.step_results:
            self.status = "pending"
            return

        total_steps = len(self.step_results)
        successful = len(self.get_successful_steps())
        failed = len(self.get_failed_steps())
        skipped = len(self.get_skipped_steps())

        if successful == total_steps:
            self.status = "completed"
        elif failed > 0:
            if successful + skipped > 0:
                self.status = "partial"  # Some steps succeeded, some failed
            else:
                self.status = "failed"
        elif any(r.status == "timeout" for r in self.step_results.values()):
            self.status = "timeout"
        else:
            self.status = "partial"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "chain_name": self.chain_name,
            "chain_db_id": self.chain_db_id,
            "status": self.status,
            "step_results": {
                step_id: result.to_dict()
                for step_id, result in self.step_results.items()
            },
            "total_execution_time": self.total_execution_time,
            "error": self.error,
            "child_chains": self.child_chains,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get human-readable summary"""
        return {
            "chain_name": self.chain_name,
            "chain_db_id": self.chain_db_id,
            "status": self.status,
            "total_steps": len(self.step_results),
            "successful": len(self.get_successful_steps()),
            "failed": len(self.get_failed_steps()),
            "skipped": len(self.get_skipped_steps()),
            "total_execution_time": self.total_execution_time,
            "child_chains_count": len(self.child_chains),
        }
