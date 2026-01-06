"""
SQLAlchemy models for artifact tracking database
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Chain(Base):
    """Represents a chain execution with versioning support"""

    __tablename__ = "chains"

    id = Column(String, primary_key=True)  # UUID
    name = Column(String, nullable=False, index=True)  # Chain name (e.g., 'image-edit-pipeline')
    description = Column(Text)
    version = Column(Integer, nullable=False, default=1)  # Incremental version number

    # Regeneration tracking
    regenerated_from_step_id = Column(String)  # Which step triggered this version (NULL for initial v1)

    # Temporal workflow info
    temporal_workflow_id = Column(String, unique=True)
    temporal_run_id = Column(String)

    # Status
    status = Column(String, nullable=False)  # 'initializing', 'executing_level_N', 'completed', 'failed', 'cancelled', 'partial'
    current_level = Column(Integer, default=0)

    # Timestamps
    started_at = Column(DateTime, nullable=False, default=func.now())
    completed_at = Column(DateTime)

    # Results
    error_message = Column(Text)
    chain_definition = Column(JSON)  # Full chain YAML as JSON

    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    workflows = relationship("Workflow", back_populates="chain", cascade="all, delete-orphan")

    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('name', 'version', name='_chain_name_version_uc'),
        Index("idx_chains_temporal", "temporal_workflow_id"),
        Index("idx_chains_name_status_version", "name", "status", "version"),
        Index("idx_chains_started", "started_at"),
    )

    def __repr__(self):
        return f"<Chain(id={self.id}, name={self.name}, status={self.status})>"


class Workflow(Base):
    """Represents individual workflow executions (steps in a chain OR standalone workflows)"""

    __tablename__ = "workflows"

    id = Column(String, primary_key=True)  # UUID

    # Chain relationship (NULL for standalone workflows)
    chain_id = Column(String, ForeignKey("chains.id", ondelete="CASCADE"))
    step_id = Column(String)  # NULL for standalone

    # Workflow info
    workflow_name = Column(String, nullable=False)
    server_address = Column(String, nullable=False)
    prompt_id = Column(String, nullable=False)

    # Temporal workflow info
    temporal_workflow_id = Column(String)
    temporal_run_id = Column(String)

    # Status
    status = Column(String, nullable=False)  # 'queued', 'executing', 'completed', 'failed', 'skipped'

    # Latest artifact reference (denormalized)
    latest_artifact_id = Column(String, ForeignKey("artifacts.id", ondelete="SET NULL"))

    # Timestamps
    queued_at = Column(DateTime, nullable=False, default=func.now())
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Execution details
    error_message = Column(Text)
    workflow_definition = Column(JSON)  # Workflow JSON sent to ComfyUI
    parameters = Column(JSON)  # Resolved parameters

    # Metadata
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    chain = relationship("Chain", back_populates="workflows")
    artifacts = relationship("Artifact", foreign_keys="Artifact.workflow_id", back_populates="workflow", cascade="all, delete-orphan")
    latest_artifact = relationship("Artifact", foreign_keys=[latest_artifact_id], post_update=True)

    # Indexes
    __table_args__ = (
        Index("idx_workflows_chain", "chain_id", "step_id"),
        Index("idx_workflows_prompt", "prompt_id"),
        Index("idx_workflows_temporal", "temporal_workflow_id"),
        Index("idx_workflows_status", "status"),
    )

    def __repr__(self):
        return f"<Workflow(id={self.id}, name={self.workflow_name}, status={self.status})>"


class Artifact(Base):
    """Tracks each output file (image, video, etc.) from workflow executions"""

    __tablename__ = "artifacts"

    id = Column(String, primary_key=True)  # UUID
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)

    # File info
    filename = Column(String, nullable=False)  # Original ComfyUI filename
    local_filename = Column(String, nullable=False, unique=True)  # Unique local filename
    local_path = Column(String, nullable=False, unique=True)  # Full path
    file_type = Column(String, nullable=False)  # 'image', 'video'
    file_format = Column(String)  # 'png', 'mp4', 'jpg'
    file_size = Column(Integer)  # Bytes

    # ComfyUI metadata
    node_id = Column(String)
    subfolder = Column(String, default="")
    comfy_folder_type = Column(String, default="output")  # 'output', 'input', 'temp'

    # Versioning
    version = Column(Integer, default=1)
    is_latest = Column(Boolean, default=True)
    parent_artifact_id = Column(String, ForeignKey("artifacts.id", ondelete="SET NULL"))

    # Approval workflow
    approval_status = Column(String, default="auto_approved")  # 'pending', 'approved', 'rejected', 'auto_approved', 'edited'
    approved_by = Column(String)
    approved_at = Column(DateTime)
    rejection_reason = Column(Text)

    # Metadata
    extra_metadata = Column(JSON)  # Additional metadata (renamed from 'metadata' to avoid SQLAlchemy conflict)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", foreign_keys=[workflow_id], back_populates="artifacts")
    parent_artifact = relationship("Artifact", remote_side=[id], backref="child_artifacts")
    transfers = relationship("ArtifactTransfer", back_populates="artifact", cascade="all, delete-orphan")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_artifacts_workflow", "workflow_id"),
        Index("idx_artifacts_latest", "workflow_id", "is_latest"),
        Index("idx_artifacts_approval", "approval_status"),
        Index("idx_artifacts_created", "created_at"),
    )

    def __repr__(self):
        return f"<Artifact(id={self.id}, filename={self.filename}, version={self.version})>"


class ArtifactTransfer(Base):
    """Tracks when artifacts are uploaded to target servers (for chaining)"""

    __tablename__ = "artifact_transfers"

    id = Column(String, primary_key=True)  # UUID
    artifact_id = Column(String, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False)

    # Transfer info
    source_workflow_id = Column(String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    target_workflow_id = Column(String, ForeignKey("workflows.id", ondelete="CASCADE"))
    target_server = Column(String, nullable=False)
    target_subfolder = Column(String, default="")

    # Status
    status = Column(String, nullable=False)  # 'pending', 'uploading', 'completed', 'failed'
    uploaded_at = Column(DateTime)
    error_message = Column(Text)

    # Metadata
    created_at = Column(DateTime, default=func.now())

    # Relationships
    artifact = relationship("Artifact", back_populates="transfers")
    source_workflow = relationship("Workflow", foreign_keys=[source_workflow_id])
    target_workflow = relationship("Workflow", foreign_keys=[target_workflow_id])

    # Indexes
    __table_args__ = (
        Index("idx_transfers_artifact", "artifact_id"),
        Index("idx_transfers_source", "source_workflow_id"),
        Index("idx_transfers_target", "target_workflow_id"),
        Index("idx_transfers_status", "status"),
    )

    def __repr__(self):
        return f"<ArtifactTransfer(id={self.id}, status={self.status})>"


class ApprovalRequest(Base):
    """Tracks approval requests for artifacts - generates link, accepts final decision, signals workflow"""

    __tablename__ = "approval_requests"

    id = Column(String, primary_key=True)  # UUID
    artifact_id = Column(String, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False)
    chain_id = Column(String, ForeignKey("chains.id", ondelete="CASCADE"))  # Optional, for chain context
    step_id = Column(String)  # Which step in the chain this approval is for

    # Temporal workflow info (parent workflow waiting for approval)
    # Multiple steps in same workflow can have separate approval requests
    temporal_workflow_id = Column(String, nullable=False)  # Workflow to signal when decision made
    temporal_run_id = Column(String)

    # Links
    approval_link_token = Column(String, unique=True, nullable=False)  # Secure token for approval URL
    artifact_view_url = Column(String, nullable=False)  # URL to view the artifact
    link_expires_at = Column(DateTime)  # Optional: link expiration

    # Status - only two final states: approved or rejected
    status = Column(String, nullable=False, default="pending")  # 'pending', 'approved', 'rejected', 'cancelled'
    decided_at = Column(DateTime)  # When final decision was made
    decided_by = Column(String)  # Optional: identifier of who/what made final decision

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Metadata
    config_metadata = Column(JSON)  # Additional configuration for external systems

    # Relationships
    artifact = relationship("Artifact", backref="approval_requests")
    chain = relationship("Chain", backref="approval_requests")

    # Indexes
    __table_args__ = (
        Index("idx_approval_requests_artifact", "artifact_id"),
        Index("idx_approval_requests_chain", "chain_id"),
        Index("idx_approval_requests_status", "status"),
        Index("idx_approval_requests_temporal", "temporal_workflow_id"),
        Index("idx_approval_requests_link_token", "approval_link_token"),
    )

    def __repr__(self):
        return f"<ApprovalRequest(id={self.id}, artifact_id={self.artifact_id}, status={self.status})>"
