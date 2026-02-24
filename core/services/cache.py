"""
Cache Service

Centralized cache management for chain execution.
Builds cache from database for regeneration/retry scenarios.
"""

from typing import Dict, Set, Optional, Any
from sqlalchemy import select, and_

from ..database.session import get_session
from ..database.models import Chain, Workflow, Artifact


def build_cache_from_database(
    chain_name: str,
    exclude_step_ids: Optional[Set[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """
    Build cache from latest completed workflows in database.

    Used for CLI regeneration - queries database for previously completed
    steps that can be reused.

    Args:
        chain_name: Name of chain to get cache from
        exclude_step_ids: Steps to exclude (step being regenerated + descendants)

    Returns:
        Dict mapping step_id to step data dict (includes output for template resolution)
    """
    cache = {}
    exclude_step_ids = exclude_step_ids or set()

    with get_session() as db:
        stmt = (
            select(Workflow)
            .join(Chain, Workflow.chain_id == Chain.id)
            .where(
                and_(
                    Chain.name == chain_name,
                    Workflow.status == 'completed'
                )
            )
            .order_by(Workflow.completed_at.desc())
        )

        workflows = db.execute(stmt).scalars().all()

        # Get latest workflow per step_id
        seen_steps = set()
        for wf in workflows:
            if wf.step_id and wf.step_id not in seen_steps and wf.step_id not in exclude_step_ids:
                # Resolve artifact metadata if present.
                artifact = None
                if wf.latest_artifact_id:
                    artifact = db.get(Artifact, wf.latest_artifact_id)
                    if not artifact:
                        continue  # Skip if artifact row is missing

                # Build output dict for template resolution and downstream references.
                output = _build_output_from_artifact(artifact)

                cache[wf.step_id] = {
                    "step_id": wf.step_id,
                    "workflow": wf.workflow_name,
                    "status": wf.status,
                    "artifact_id": wf.latest_artifact_id,
                    "workflow_db_id": wf.id,
                    "server_address": wf.server_address,
                    "parameters": wf.parameters or {},
                    "output": output,
                }
                seen_steps.add(wf.step_id)

    return cache


def _build_output_from_artifact(artifact: Optional[Artifact]) -> Optional[Dict[str, Any]]:
    """
    Build output dict from artifact for template resolution.

    Templates like {{ step1.output.image }} need the output dict.
    """
    if not artifact:
        return None

    asset_ref = None
    asset_id = None
    if isinstance(artifact.extra_metadata, dict):
        candidate = artifact.extra_metadata.get("asset_ref")
        if isinstance(candidate, dict):
            asset_ref = candidate
        candidate_asset_id = artifact.extra_metadata.get("asset_id")
        if isinstance(candidate_asset_id, str) and candidate_asset_id.strip():
            asset_id = candidate_asset_id.strip()
    if isinstance(asset_ref, dict):
        ref_asset_id = asset_ref.get("asset_id")
        if isinstance(ref_asset_id, str) and ref_asset_id.strip():
            asset_id = ref_asset_id.strip()

    # Asset-first output shape (matches comfy executor output contract).
    if not asset_ref and asset_id:
        asset_ref = {"asset_id": asset_id}

    if asset_ref and asset_id:
        return {
            "type": "asset",
            "output": asset_id,
            "asset_id": asset_id,
            "asset_ref": asset_ref,
            "assets": [{"asset_id": asset_id, "asset_ref": asset_ref}],
            "count": 1,
        }

    filename = artifact.filename
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("mp4", "webm", "mov", "avi"):
        return {"video": filename, "type": "video"}
    else:
        return {"image": filename, "type": "image"}
