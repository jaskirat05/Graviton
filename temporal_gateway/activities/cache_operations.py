"""
Cache Operations Activities

Activities for building cache from database and managing chain versions.
"""

import os
from typing import Dict, Optional, List
from temporalio import activity
from sqlalchemy import select, and_, desc
from sqlalchemy.orm import Session

from ..database.session import get_session
from ..database.models import Chain, Workflow, Artifact
from ..chains.models import StepResult


@activity.defn
async def build_cache_from_database(
    chain_name: str,
    exclude_step_id: Optional[str] = None
) -> Dict[str, Dict]:
    """
    Build cache from latest completed workflows in database

    Queries database for the most recent completed execution of each step
    in the specified chain, regardless of which chain version they came from.

    Args:
        chain_name: Name of chain to get cache from
        exclude_step_id: Step to exclude (the one being regenerated)

    Returns:
        Dict mapping step_id to StepResult dict
    """
    activity.logger.info(f"Building cache from database for chain: {chain_name}")

    cache = {}

    with get_session() as db:
        # Get all distinct step_ids that have completed for this chain
        # We need the latest completed workflow for each step

        # Subquery to get latest workflow per step
        from sqlalchemy import func

        # Get workflows for this chain name
        stmt = (
            select(Workflow)
            .join(Chain, Workflow.chain_id == Chain.id)
            .where(
                and_(
                    Chain.name == chain_name,
                    Workflow.status == 'completed',
                    Workflow.step_id != exclude_step_id if exclude_step_id else True
                )
            )
            .order_by(Workflow.completed_at.desc())
        )

        workflows = db.execute(stmt).scalars().all()

        # Get latest workflow per step_id
        seen_steps = set()
        for wf in workflows:
            if wf.step_id and wf.step_id not in seen_steps:
                # Check if artifact still exists
                artifact_valid = True
                if wf.latest_artifact_id:
                    artifact = db.get(Artifact, wf.latest_artifact_id)
                    if not artifact or not os.path.exists(artifact.local_path):
                        activity.logger.warning(
                            f"Artifact {wf.latest_artifact_id} for step {wf.step_id} not found, will re-execute"
                        )
                        artifact_valid = False

                if artifact_valid:
                    cache[wf.step_id] = {
                        "step_id": wf.step_id,
                        "workflow": wf.workflow_name,
                        "status": wf.status,
                        "artifact_id": wf.latest_artifact_id,
                        "workflow_db_id": wf.id,
                        "server_address": wf.server_address,
                        "parameters": {},  # Would need to store this in Workflow table
                    }
                    seen_steps.add(wf.step_id)

    activity.logger.info(f"Built cache with {len(cache)} steps: {list(cache.keys())}")
    return cache


@activity.defn
async def get_next_chain_version(chain_name: str) -> int:
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

        activity.logger.info(f"Next version for chain '{chain_name}': {next_version}")
        return next_version


@activity.defn
async def get_chain_by_name_version(chain_name: str, version: Optional[int] = None) -> Optional[Dict]:
    """
    Get chain by name and version

    Args:
        chain_name: Chain name
        version: Version number (None = latest completed)

    Returns:
        Chain dict or None if not found
    """
    with get_session() as db:
        if version:
            # Get specific version
            stmt = select(Chain).where(
                and_(Chain.name == chain_name, Chain.version == version)
            )
        else:
            # Get latest completed version
            stmt = (
                select(Chain)
                .where(
                    and_(
                        Chain.name == chain_name,
                        Chain.status.in_(['completed', 'partial'])
                    )
                )
                .order_by(Chain.version.desc())
                .limit(1)
            )

        chain = db.execute(stmt).scalar_one_or_none()

        if chain:
            return {
                "id": chain.id,
                "name": chain.name,
                "version": chain.version,
                "status": chain.status,
                "regenerated_from_step_id": chain.regenerated_from_step_id,
                "temporal_workflow_id": chain.temporal_workflow_id,
                "started_at": chain.started_at.isoformat() if chain.started_at else None,
                "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
            }

        return None
