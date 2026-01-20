"""
Cache Operations Activities

Temporal activities for cache operations. Uses centralized cache service.
"""

from typing import Dict, Optional, Set
from temporalio import activity

from ..services.cache import build_cache_from_database as _build_cache


@activity.defn
async def build_cache_from_database(
    chain_name: str,
    exclude_step_ids: Optional[Set[str]] = None
) -> Dict[str, Dict]:
    """
    Activity: Build cache from database for chain regeneration.

    Args:
        chain_name: Name of chain to get cache from
        exclude_step_ids: Steps to exclude (being regenerated + descendants)

    Returns:
        Dict mapping step_id to step data dict
    """
    activity.logger.info(f"Building cache for chain: {chain_name}")

    cache = _build_cache(chain_name, exclude_step_ids)

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
                "job_id": chain.job_id,
                "started_at": chain.started_at.isoformat() if chain.started_at else None,
                "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
            }

        return None
