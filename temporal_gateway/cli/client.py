"""
Gateway HTTP Client

Async client for communicating with the ComfyChain gateway API.
"""

import httpx
from typing import Dict, Any, Optional


class GatewayClient:
    """HTTP client for the ComfyChain gateway API"""

    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def health(self) -> Dict[str, Any]:
        """Check gateway health"""
        client = await self._get_client()
        response = await client.get("/health")
        response.raise_for_status()
        return response.json()

    async def calculate_hash(self, chain: Dict[str, Any]) -> str:
        """Calculate hash for a chain definition"""
        client = await self._get_client()
        response = await client.post("/chains/hash", json={"chain": chain})
        response.raise_for_status()
        return response.json().get("hash")

    async def get_chain_by_hash(self, definition_hash: str) -> Dict[str, Any]:
        """Look up chains by definition hash"""
        client = await self._get_client()
        response = await client.get(f"/chains/by-hash/{definition_hash}")
        response.raise_for_status()
        return response.json()

    async def execute_chain(
        self, chain: Dict[str, Any], parameters: Optional[Dict[str, Any]] = None, force: bool = False
    ) -> Dict[str, Any]:
        """Execute a workflow chain"""
        client = await self._get_client()
        response = await client.post(
            "/chains/execute",
            params={"force": str(force).lower()},
            json={"chain": chain, "parameters": parameters or {}},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()

    async def get_status(self, job_id: str) -> Dict[str, Any]:
        """Get chain execution status

        Args:
            job_id: Job ID (Temporal workflow ID) returned from execute_chain
        """
        client = await self._get_client()
        response = await client.get(f"/chains/status/{job_id}")
        response.raise_for_status()
        return response.json()

    async def get_result(self, job_id: str) -> Dict[str, Any]:
        """Wait for chain to complete and get result

        Args:
            job_id: Job ID (Temporal workflow ID) returned from execute_chain
        """
        client = await self._get_client()
        response = await client.get(f"/chains/result/{job_id}", timeout=600.0)
        response.raise_for_status()
        return response.json()

    async def regenerate_chain(
        self,
        definition_hash: str,
        from_step: str,
        new_parameters: Optional[Dict[str, Any]] = None,
        chain_definition: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Regenerate chain from a specific step using definition hash.

        Args:
            definition_hash: Hash to look up cached results from
            from_step: Step to regenerate from
            new_parameters: New parameters for changed steps
            chain_definition: Current chain definition (uses this instead of stored DB definition)
        """
        client = await self._get_client()
        response = await client.post(
            "/chains/regenerate",
            json={
                "definition_hash": definition_hash,
                "from_step": from_step,
                "new_parameters": new_parameters or {},
                "chain_definition": chain_definition,
            },
        )
        response.raise_for_status()
        return response.json()

    # Approval endpoints
    async def list_pending_approvals(self) -> Dict[str, Any]:
        """List pending approval requests"""
        client = await self._get_client()
        response = await client.get("/approval/pending")
        response.raise_for_status()
        return response.json()

    async def get_approval(self, token: str) -> Dict[str, Any]:
        """Get approval request details"""
        client = await self._get_client()
        response = await client.get(f"/approval/{token}")
        response.raise_for_status()
        return response.json()

    async def get_approval_parameters(self, token: str) -> Dict[str, Any]:
        """Get editable parameters for an approval request"""
        client = await self._get_client()
        response = await client.get(f"/approval/{token}/parameters")
        response.raise_for_status()
        return response.json()

    async def approve_request(self, token: str, decided_by: str) -> Dict[str, Any]:
        """Approve a pending request"""
        client = await self._get_client()
        response = await client.post(
            f"/approval/{token}/approve", json={"decided_by": decided_by}
        )
        response.raise_for_status()
        return response.json()

    async def reject_request(
        self,
        token: str,
        decided_by: str,
        from_step: Optional[str] = None,
        new_parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Reject a pending request with optional regeneration"""
        client = await self._get_client()
        payload = {"decided_by": decided_by}
        if new_parameters:
            payload["parameters"] = new_parameters

        response = await client.post(f"/approval/{token}/reject", json=payload)
        response.raise_for_status()
        return response.json()
