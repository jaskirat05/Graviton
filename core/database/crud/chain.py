"""
CRUD operations for Chain model
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..models import Chain


def create_chain(
    session: Session,
    name: str,
    status: str = "initializing",
    job_id: Optional[str] = None,
    job_run_id: Optional[str] = None,
    chain_definition: Optional[Dict[str, Any]] = None,
    definition_hash: Optional[str] = None,
    description: Optional[str] = None,
    regenerated_from_step_id: Optional[str] = None,
) -> Chain:
    """Create a new chain execution record with auto-incrementing version"""
    # Get next version number for this chain name
    latest = session.query(Chain).filter(
        Chain.name == name
    ).order_by(desc(Chain.version)).first()

    next_version = (latest.version + 1) if latest else 1

    chain = Chain(
        id=str(uuid.uuid4()),
        name=name,
        version=next_version,
        description=description,
        job_id=job_id,
        job_run_id=job_run_id,
        status=status,
        chain_definition=chain_definition,
        definition_hash=definition_hash,
        regenerated_from_step_id=regenerated_from_step_id,
        started_at=datetime.utcnow(),
    )
    session.add(chain)
    session.commit()
    session.refresh(chain)
    return chain


def get_chain(session: Session, chain_id: str) -> Optional[Chain]:
    """Get chain by ID"""
    return session.query(Chain).filter(Chain.id == chain_id).first()


def get_chain_by_job_id(session: Session, job_id: str) -> Optional[Chain]:
    """Get chain by job ID"""
    return session.query(Chain).filter(Chain.job_id == job_id).first()


def update_chain_status(
    session: Session,
    chain_id: str,
    status: str,
    current_level: Optional[int] = None,
    error_message: Optional[str] = None,
) -> Optional[Chain]:
    """Update chain status"""
    chain = get_chain(session, chain_id)
    if not chain:
        return None

    chain.status = status
    if current_level is not None:
        chain.current_level = current_level
    if error_message:
        chain.error_message = error_message
    if status in ["completed", "failed", "cancelled"]:
        chain.completed_at = datetime.utcnow()

    session.commit()
    session.refresh(chain)
    return chain


def list_chains(
    session: Session,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
) -> List[Chain]:
    """List chains with optional filtering"""
    query = session.query(Chain)
    if status:
        query = query.filter(Chain.status == status)
    return query.order_by(desc(Chain.started_at)).limit(limit).offset(offset).all()


def delete_chain(session: Session, chain_id: str) -> bool:
    """Delete a chain and all associated workflows/artifacts (cascade)"""
    chain = get_chain(session, chain_id)
    if not chain:
        return False

    session.delete(chain)
    session.commit()
    return True


def save_executed_definition(
    session: Session,
    chain_id: str,
    executed_definition: Dict[str, Any],
) -> Optional[Chain]:
    """
    Save the executed definition (with actual parameters used) to the chain.

    Called after chain completion to persist the final state including
    any parameter updates that were made during execution.

    Args:
        session: Database session
        chain_id: Chain ID
        executed_definition: Final chain definition with actual executed parameters

    Returns:
        Updated Chain or None if not found
    """
    chain = get_chain(session, chain_id)
    if not chain:
        return None

    chain.executed_definition = executed_definition
    session.commit()
    session.refresh(chain)
    return chain


def get_chain_by_hash(
    session: Session,
    definition_hash: str,
    name: Optional[str] = None,
) -> Optional[Chain]:
    """
    Get the latest chain with matching definition hash.

    Used for cache lookup - find previous executions of the same definition.

    Args:
        session: Database session
        definition_hash: Hash of chain definition
        name: Optional chain name filter (for extra safety)

    Returns:
        Latest matching Chain or None
    """
    query = session.query(Chain).filter(
        Chain.definition_hash == definition_hash
    )
    if name:
        query = query.filter(Chain.name == name)

    return query.order_by(desc(Chain.version)).first()


def get_chains_by_hash(
    session: Session,
    definition_hash: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
) -> List[Chain]:
    """
    Get all chains with matching definition hash.

    Args:
        session: Database session
        definition_hash: Hash of chain definition
        name: Optional chain name filter
        status: Optional status filter (e.g., 'completed')
        limit: Maximum results

    Returns:
        List of matching chains, newest first
    """
    query = session.query(Chain).filter(
        Chain.definition_hash == definition_hash
    )
    if name:
        query = query.filter(Chain.name == name)
    if status:
        query = query.filter(Chain.status == status)

    return query.order_by(desc(Chain.version)).limit(limit).all()
