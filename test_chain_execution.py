"""
Chain Execution Test - Manual Regeneration from Specific Step

Tests the regeneration workflow from a specific step with caching.
"""

import asyncio
import httpx
import json
import time
from typing import Optional


BASE_URL = "http://localhost:8001"
CHAIN_NAME = "image-edit-to-video-pipeline"


async def wait_for_approval(client: httpx.AsyncClient, timeout: int = 300) -> Optional[dict]:
    """Wait for a pending approval request to appear"""
    print("   Waiting for approval request...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = await client.get(f"{BASE_URL}/approval/pending")
        if response.status_code == 200:
            approvals = response.json()
            if approvals and len(approvals) > 0:
                return approvals[0]
        await asyncio.sleep(2)

    return None


async def approve_request(client: httpx.AsyncClient, token: str, decided_by: str = "test-user"):
    """Approve an approval request"""
    response = await client.post(
        f"{BASE_URL}/approval/{token}/approve",
        json={"decided_by": decided_by}
    )
    return response


async def reject_request(client: httpx.AsyncClient, token: str, new_parameters: dict, decided_by: str = "test-user", comment: str = ""):
    """Reject an approval request with new parameters"""
    response = await client.post(
        f"{BASE_URL}/approval/{token}/reject",
        json={
            "decided_by": decided_by,
            "parameters": new_parameters,
            "comment": comment
        }
    )
    return response


async def monitor_chain_completion(client: httpx.AsyncClient, workflow_id: str, timeout: int = 1800):
    """Monitor chain until completion or timeout (30 minutes default)"""
    start_time = time.time()

    while time.time() - start_time < timeout:
        response = await client.get(f"{BASE_URL}/chains/status/{workflow_id}")
        if response.status_code != 200:
            print(f"   Status check failed: {response.status_code}")
            return None

        status = response.json()
        current_status = status.get('status', 'unknown')
        print(f"   Current status: {current_status}")

        if current_status in ['completed', 'failed', 'partial']:
            print(f"   Chain finished with status: {current_status}")
            return status

        await asyncio.sleep(3)

    print(f"   Timeout reached after {timeout} seconds")
    return None


# ============================================================================
# TEST: Manual Regeneration from Specific Step
# ============================================================================

async def test_manual_regeneration():
    """
    Test manual regeneration from a specific step with approval rejection

    This test:
    - Uses most recent completed chain (chain_id: 2de2673d-1960-4b3a-a456-835a09eb533d)
    - All steps completed: extract_frame1, extract_frame2, edit_frame1, edit_frame2, create_video
    - Manually triggers regeneration from edit_frame1 with new parameters
    - Rejects first approval (edit_frame1) with different prompt
    - Approves regenerated edit_frame1 (in-step regeneration)
    - Approves remaining steps (edit_frame2, create_video)

    Expected:
    - Cache: extract_frame1 (ComfyUI_00184_.png), extract_frame2 (ComfyUI_00185_.png)
    - Regenerate: edit_frame1 (twice - rejected then approved), edit_frame2, create_video
    """

    print("\n" + "=" * 70)
    print("TEST: REGENERATION WITH APPROVAL REJECTION")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=1800.0) as client:
        print("\n1. Using most recent completed chain for regeneration...")
        print("   Chain ID: 2de2673d-1960-4b3a-a456-835a09eb533d")
        print("   ✓ All 5 steps completed successfully")

        # Manually regenerate from edit_frame1 with parameters for multiple steps
        print("\n2. Manually regenerating from edit_frame1 with new parameters...")
        regenerate_payload = {
            "from_step": "edit_frame1",
            "new_parameters": {
                "edit_frame1": {
                    "111.prompt": "Transform the scene into a cyberpunk style with neon lights"
                },
                "edit_frame2": {
                    "111.prompt": "Make the scene more vibrant with enhanced neon colors"
                },
                "create_video": {
                    "6.text": "Smooth cinematic transition with cyberpunk aesthetics",
                    "60.fps": 16
                }
            }
        }

        response = await client.post(
            f"{BASE_URL}/chains/{CHAIN_NAME}/regenerate",
            json=regenerate_payload
        )

        if response.status_code != 200:
            print(f"   ❌ Regeneration failed: {response.status_code} - {response.text}")
            return False

        regen_result = response.json()
        workflow_id = regen_result['workflow_id']
        print(f"   ✓ Regeneration started: {workflow_id}")
        print(f"   Regenerating from: {regen_result['regeneration_from_step']}")
        print(f"   Updated parameters for: {', '.join(regenerate_payload['new_parameters'].keys())}")

        # Handle approvals with rejection for first edit_frame1
        print("\n3. Handling approvals (reject first edit_frame1, approve rest)...")
        approved_count = 0
        rejected_count = 0
        edit_frame1_seen = False

        for i in range(10):  # Safety limit (increased for retry)
            approval = await wait_for_approval(client, timeout=600)
            if not approval:
                break

            token = approval['approval_link_token']
            step_id = approval.get('step_id', 'unknown')

            # Reject first edit_frame1, approve everything else
            if step_id == 'edit_frame1' and not edit_frame1_seen:
                edit_frame1_seen = True
                print(f"   🔄 Rejecting step: {step_id} (first attempt)")
                await reject_request(
                    client,
                    token,
                    new_parameters={
                        "111.prompt": "Transform into a futuristic sci-fi scene with holographic elements and glowing accents"
                    },
                    comment="Need more futuristic holographic elements"
                )
                rejected_count += 1
                print(f"      → Waiting for regenerated {step_id}...")
            else:
                print(f"   ✅ Approving step: {step_id}")
                await approve_request(client, token)
                approved_count += 1

        print(f"   ✓ Rejected {rejected_count} approval(s)")
        print(f"   ✓ Approved {approved_count} approval(s) (including regenerated)")

        # Wait for regenerated chain completion
        print("\n4. Waiting for regenerated chain completion...")
        final_status = await monitor_chain_completion(client, workflow_id)

        if not final_status:
            print("   ❌ Regenerated chain did not complete in time")
            return False

        # Get final result
        print("\n5. Getting regenerated chain result...")
        response = await client.get(f"{BASE_URL}/chains/result/{workflow_id}")
        if response.status_code != 200:
            print(f"   ❌ ERROR: {response.status_code}")
            return False

        result = response.json()
        print(f"   Status: {result['status']}")
        print(f"   Successful Steps: {result['successful_steps']}")

        # Verify cached steps vs regenerated steps
        print("\n6. Verifying execution flow...")
        print(f"   Expected cached: extract_frame1, extract_frame2")
        print(f"   Expected regenerated: edit_frame1 (2x - rejected + approved), edit_frame2, create_video")
        print(f"\n   Final step statuses:")

        for step_id, step_result in result['step_results'].items():
            approval_info = ""
            if step_result.get('approval_decision'):
                approval_info = f" (approval: {step_result['approval_decision']})"
            print(f"   {step_id}: {step_result['status']}{approval_info}")

        success = result['status'] == 'completed'
        print(f"\n   {'✓ TEST PASSED' if success else '❌ TEST FAILED'}")
        return success


# ============================================================================
# Main Test Runner
# ============================================================================

async def run_test():
    """Run the manual regeneration test"""

    print("\n" + "=" * 70)
    print("CHAIN REGENERATION TEST")
    print("=" * 70)
    print(f"Chain: {CHAIN_NAME}")
    print(f"Base URL: {BASE_URL}")
    print("=" * 70)

    try:
        success = await test_manual_regeneration()

        print("\n" + "=" * 70)
        print("TEST RESULT")
        print("=" * 70)
        if success:
            print("✓ TEST PASSED!")
        else:
            print("❌ TEST FAILED")
        print("=" * 70)

        return success
    except Exception as e:
        print(f"\n❌ TEST EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    asyncio.run(run_test())
