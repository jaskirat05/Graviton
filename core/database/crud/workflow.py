"""
CRUD operations for Workflow model
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from ..models import Workflow


def create_workflow(
    session: Session,
    workflow_name: str,
    server_address: str,
    prompt_id: str,
    status: str = "queued",
    chain_id: Optional[str] = None,
    step_id: Optional[str] = None,
    job_id: Optional[str] = None,
    job_run_id: Optional[str] = None,
    workflow_definition: Optional[Dict[str, Any]] = None,
    parameters: Optional[Dict[str, Any]] = None,
) -> Workflow:
    """Create a new workflow execution record"""
    workflow = Workflow(
        id=str(uuid.uuid4()),
        chain_id=chain_id,
        step_id=step_id,
        workflow_name=workflow_name,
        server_address=server_address,
        prompt_id=prompt_id,
        job_id=job_id,
        job_run_id=job_run_id,
        status=status,
        workflow_definition=workflow_definition,
        parameters=parameters,
        queued_at=datetime.utcnow(),
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    return workflow


def get_workflow(session: Session, workflow_id: str) -> Optional[Workflow]:
    """Get workflow by ID"""
    return session.query(Workflow).filter(Workflow.id == workflow_id).first()


def get_workflow_by_prompt(session: Session, prompt_id: str) -> Optional[Workflow]:
    """Get workflow by ComfyUI prompt ID"""
    return session.query(Workflow).filter(Workflow.prompt_id == prompt_id).first()


def get_workflow_by_step(
    session: Session,
    chain_id: str,
    step_id: str,
) -> Optional[Workflow]:
    """Get workflow by chain ID and step ID"""
    return session.query(Workflow).filter(
        and_(Workflow.chain_id == chain_id, Workflow.step_id == step_id)
    ).first()


def get_workflows_by_chain(
    session: Session,
    chain_id: str,
) -> List[Workflow]:
    """Get all workflows in a chain"""
    return session.query(Workflow).filter(Workflow.chain_id == chain_id).all()


def update_workflow_status(
    session: Session,
    workflow_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> Optional[Workflow]:
    """Update workflow status"""
    workflow = get_workflow(session, workflow_id)
    if not workflow:
        return None

    workflow.status = status
    if status == "executing" and not workflow.started_at:
        workflow.started_at = datetime.utcnow()
    if status in ["completed", "failed", "skipped"]:
        workflow.completed_at = datetime.utcnow()
    if error_message:
        workflow.error_message = error_message

    session.commit()
    session.refresh(workflow)
    return workflow


def update_workflow_latest_artifact(
    session: Session,
    workflow_id: str,
    artifact_id: str,
) -> Optional[Workflow]:
    """Update workflow's latest artifact reference"""
    workflow = get_workflow(session, workflow_id)
    if not workflow:
        return None

    workflow.latest_artifact_id = artifact_id
    session.commit()
    session.refresh(workflow)
    return workflow


def list_workflows(
    session: Session,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    chain_id: Optional[str] = None,
) -> List[Workflow]:
    """List workflows with optional filtering"""
    query = session.query(Workflow)
    if status:
        query = query.filter(Workflow.status == status)
    if chain_id:
        query = query.filter(Workflow.chain_id == chain_id)
    return query.order_by(desc(Workflow.queued_at)).limit(limit).offset(offset).all()


def delete_workflow(session: Session, workflow_id: str) -> bool:
    """Delete a workflow and all associated artifacts (cascade)"""
    workflow = get_workflow(session, workflow_id)
    if not workflow:
        return False

    session.delete(workflow)
    session.commit()
    return True
