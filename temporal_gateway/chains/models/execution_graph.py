"""
Execution Graph Models

Graph-based execution models using NetworkX for dependency management.
"""

from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
import networkx as nx


@dataclass
class StepNode:
    """
    Represents a single node in the execution graph

    This is the runtime execution unit that tracks:
    - What to execute (workflow, parameters)
    - Dependencies (what must complete first)
    - Execution state (status, results, artifacts)
    - Approval requirements

    Attributes:
        step_id: Unique step identifier
        workflow: Workflow name to execute
        parameters: Parameters with Jinja2 templates (resolved at runtime)
        condition: Optional condition expression
        dependencies: Set of step IDs this node depends on
        requires_approval: Whether this step requires approval
        approval_config: Approval configuration (timeout, retry, etc.)

        # Runtime state
        status: Current execution status
        artifact_id: Database artifact ID produced by this step
        workflow_db_id: Database workflow ID for this execution
        server_address: Server where this step executed
        error: Error message if failed
        skipped_reason: Reason if step was skipped
    """
    # Definition (from YAML)
    step_id: str
    workflow: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    condition: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)  # List for serialization compatibility
    requires_approval: bool = False
    approval_config: Dict[str, Any] = field(default_factory=dict)

    # Runtime state
    status: str = "pending"  # pending, executing, completed, failed, skipped_condition, skipped_dependency, timeout, rejected
    artifact_id: Optional[int] = None  # Single artifact produced by this step
    workflow_db_id: Optional[int] = None
    server_address: Optional[str] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None

    def is_ready(self, completed_steps: Set[str]) -> bool:
        """Check if all dependencies are satisfied"""
        return set(self.dependencies).issubset(completed_steps)

    def is_terminal_state(self) -> bool:
        """Check if node is in a terminal state (won't execute further)"""
        return self.status in ["completed", "failed", "skipped_condition", "skipped_dependency", "timeout"]

    def is_successful(self) -> bool:
        """Check if node completed successfully"""
        return self.status == "completed"

    def mark_skipped_condition(self, reason: str):
        """Mark node as skipped due to condition"""
        self.status = "skipped_condition"
        self.skipped_reason = reason

    def mark_skipped_dependency(self, dependency_id: str):
        """Mark node as skipped due to missing dependency"""
        self.status = "skipped_dependency"
        self.skipped_reason = f"Dependency '{dependency_id}' was not satisfied"

    def mark_timeout(self):
        """Mark node as timed out"""
        self.status = "timeout"
        self.error = "Approval timeout reached"

    def mark_rejected(self, reason: str = "Approval rejected and max retries exhausted"):
        """Mark node as rejected"""
        self.status = "rejected"
        self.error = reason

    def mark_completed(self, artifact_id: Optional[int] = None, workflow_db_id: Optional[int] = None):
        """Mark node as successfully completed"""
        self.status = "completed"
        self.artifact_id = artifact_id
        self.workflow_db_id = workflow_db_id

    def mark_failed(self, error: str):
        """Mark node as failed"""
        self.status = "failed"
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "step_id": self.step_id,
            "workflow": self.workflow,
            "parameters": self.parameters,
            "condition": self.condition,
            "dependencies": self.dependencies,  # Already a list
            "requires_approval": self.requires_approval,
            "approval_config": self.approval_config,
            "status": self.status,
            "artifact_id": self.artifact_id,
            "workflow_db_id": self.workflow_db_id,
            "server_address": self.server_address,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
        }


@dataclass
class ExecutionGraph:
    """
    Directed Acyclic Graph (DAG) for chain execution using NetworkX

    This is the core execution structure that:
    - Manages dependency relationships between steps
    - Provides graph traversal operations (descendants, ancestors)
    - Calculates parallel execution levels
    - Tracks execution state
    - Validates cache for step reuse

    Attributes:
        chain_name: Name of the chain
        nodes: Dict mapping step_id to StepNode
        chain_db_id: Database chain ID (once saved)

    Note:
        graph (NetworkX DiGraph) is built dynamically in __post_init__ and is NOT
        serialized. It's reconstructed from nodes on deserialization.
    """
    chain_name: str
    nodes: Dict[str, StepNode] = field(default_factory=dict)
    chain_db_id: Optional[int] = None

    def __post_init__(self):
        """Initialize the NetworkX graph from nodes"""
        # Build graph from nodes (not a dataclass field, so won't be serialized)
        self.graph = nx.DiGraph()
        for step_id, node in self.nodes.items():
            self.graph.add_node(step_id, node=node)
            for dep_id in node.dependencies:
                self.graph.add_edge(dep_id, step_id)

    def add_node(self, node: StepNode):
        """Add a step node to the graph"""
        self.nodes[node.step_id] = node
        self.graph.add_node(node.step_id, node=node)

        # Add edges for dependencies
        for dep_id in node.dependencies:
            self.graph.add_edge(dep_id, node.step_id)

    def get_node(self, step_id: str) -> Optional[StepNode]:
        """Get node by step ID"""
        return self.nodes.get(step_id)

    def get_descendants(self, step_id: str) -> Set[str]:
        """
        Get all descendants (children, grandchildren, etc.) of a step

        Args:
            step_id: Starting step ID

        Returns:
            Set of all descendant step IDs
        """
        try:
            return nx.descendants(self.graph, step_id)
        except nx.NetworkXError:
            return set()

    def get_ancestors(self, step_id: str) -> Set[str]:
        """
        Get all ancestors (parents, grandparents, etc.) of a step

        Args:
            step_id: Target step ID

        Returns:
            Set of all ancestor step IDs
        """
        try:
            return nx.ancestors(self.graph, step_id)
        except nx.NetworkXError:
            return set()


    def get_execution_levels(self) -> List[List[str]]:
        """
        Get parallel execution levels using topological sort

        Returns:
            List of lists, where each inner list contains step IDs
            that can execute in parallel.

        Example:
            [[A], [B, C], [D]]
            - Level 0: A (no dependencies)
            - Level 1: B, C (both depend only on A, can run in parallel)
            - Level 2: D (depends on B and/or C)
        """
        return list(nx.topological_generations(self.graph))

    def validate_dag(self) -> bool:
        """
        Validate that graph is a valid DAG (no cycles)

        Returns:
            True if valid DAG

        Raises:
            ValueError: If graph contains cycles
        """
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            raise ValueError(f"Graph contains circular dependencies: {cycles}")
        return True

    def get_ready_nodes(self, completed_steps: Set[str]) -> List[StepNode]:
        """
        Get all nodes that are ready to execute

        A node is ready if:
        - It's in pending state
        - All its dependencies are in completed_steps

        Args:
            completed_steps: Set of step IDs that have completed

        Returns:
            List of StepNode objects ready for execution
        """
        ready = []
        for node in self.nodes.values():
            if node.status == "pending" and node.is_ready(completed_steps):
                ready.append(node)
        return ready

    def get_immediate_children(self, step_id: str) -> Set[str]:
        """Get direct children (immediate descendants) of a step"""
        return set(self.graph.successors(step_id))

    def get_immediate_parents(self, step_id: str) -> Set[str]:
        """Get direct parents (immediate dependencies) of a step"""
        return set(self.graph.predecessors(step_id))

    def get_leaf_nodes(self) -> List[str]:
        """Get all leaf nodes (nodes with no children)"""
        return [node for node in self.graph.nodes() if self.graph.out_degree(node) == 0]

    def get_root_nodes(self) -> List[str]:
        """Get all root nodes (nodes with no dependencies)"""
        return [node for node in self.graph.nodes() if self.graph.in_degree(node) == 0]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "chain_name": self.chain_name,
            "nodes": {step_id: node.to_dict() for step_id, node in self.nodes.items()},
            "edges": list(self.graph.edges()),
            "chain_db_id": self.chain_db_id,
        }

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get human-readable execution summary"""
        levels = self.get_execution_levels()
        return {
            "chain_name": self.chain_name,
            "total_steps": len(self.nodes),
            "total_levels": len(levels),
            "parallel_groups": levels,
            "execution_order": [node for level in levels for node in level],
            "status_breakdown": self._get_status_breakdown(),
        }

    def _get_status_breakdown(self) -> Dict[str, int]:
        """Get count of nodes in each status"""
        breakdown = {}
        for node in self.nodes.values():
            breakdown[node.status] = breakdown.get(node.status, 0) + 1
        return breakdown

    def apply_cached_result(self, step_id: str, cached_result: 'StepResult'):
        """
        Apply a cached result to a node

        Args:
            step_id: Step ID to apply cache to
            cached_result: Cached result from database
        """
        node = self.get_node(step_id)
        if node:
            node.status = cached_result.status
            node.artifact_id = cached_result.artifact_id
            node.workflow_db_id = cached_result.workflow_db_id
            node.server_address = cached_result.server_address

    def propagate_skip(self, step_id: str, reason: str = "dependency"):
        """
        Propagate skip status to all descendants of a step

        When a step fails, is rejected, or skipped due to condition,
        all its descendants must also be skipped.

        Args:
            step_id: Step that failed/was skipped
            reason: Reason for skip (for logging)
        """
        descendants = self.get_descendants(step_id)

        for desc_id in descendants:
            desc_node = self.get_node(desc_id)
            if desc_node and desc_node.status == "pending":
                desc_node.mark_skipped_dependency(step_id)

    def build_step_result_from_node(self, step_id: str) -> Optional['StepResult']:
        """
        Build a StepResult from a completed node

        Args:
            step_id: Step ID to build result for

        Returns:
            StepResult if node is completed, None otherwise
        """
        from .execution_result import StepResult

        node = self.get_node(step_id)
        if not node or not node.is_successful():
            return None

        return StepResult(
            step_id=node.step_id,
            workflow=node.workflow,
            status=node.status,
            artifact_id=node.artifact_id,
            workflow_db_id=node.workflow_db_id,
            server_address=node.server_address,
            parameters=node.parameters,
        )

    def update_step_with_new_parameters(self, step_id: str, new_parameters: Dict[str, Any]):
        """
        Update a step's parameters (used when rejection provides new params)

        Args:
            step_id: Step to update
            new_parameters: New parameter values
        """
        node = self.get_node(step_id)
        if node:
            node.parameters.update(new_parameters)
            node.status = "pending"  # Reset to pending for re-execution
            # Version will increment when re-executed
