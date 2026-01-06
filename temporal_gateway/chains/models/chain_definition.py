"""
Chain Definition Models

Models for defining chains from YAML files.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, validator


class ChainStepDefinition(BaseModel):
    """
    Represents a single step in a chain definition (from YAML)

    Attributes:
        id: Unique step identifier
        workflow: Name of the workflow to execute
        parameters: Parameters to pass to the workflow (can contain Jinja2 templates)
        depends_on: List of step IDs this step depends on
        condition: Optional Jinja2 expression to evaluate before executing
        description: Optional human-readable description
        requires_approval: Whether this step requires approval before proceeding
        approval: Approval configuration (timeout, retry policy, etc.)
    """
    id: str = Field(..., description="Unique step identifier")
    workflow: str = Field(..., description="Workflow name to execute")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Workflow parameters")
    depends_on: List[str] = Field(default_factory=list, description="Step IDs this depends on")
    condition: Optional[str] = Field(None, description="Jinja2 condition expression")
    description: Optional[str] = Field(None, description="Step description")
    requires_approval: bool = Field(False, description="Whether approval is required")
    approval: Dict[str, Any] = Field(default_factory=dict, description="Approval configuration")

    @validator('id')
    def validate_id(cls, v):
        """Ensure step ID is valid"""
        if not v or not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError(f"Invalid step ID: {v}. Must be alphanumeric with _ or -")
        return v


class ChainDefinition(BaseModel):
    """
    Represents a complete chain definition (from YAML)

    Attributes:
        name: Chain name
        description: Human-readable description
        steps: List of steps in the chain
        metadata: Optional metadata (tags, version, etc.)
    """
    name: str = Field(..., description="Chain name")
    description: Optional[str] = Field(None, description="Chain description")
    steps: List[ChainStepDefinition] = Field(..., description="Chain steps")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional metadata")

    @validator('steps')
    def validate_steps(cls, steps):
        """Ensure step IDs are unique"""
        step_ids = [step.id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Duplicate step IDs found")
        return steps
