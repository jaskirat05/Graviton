"""
Chain Execution Test - Flux Dev to Qwen Image Edit Pipeline

Interactive test with approval flow - shows artifact URLs and allows approve/reject.
"""

import asyncio
import httpx
import json
import time
import yaml
from pathlib import Path
from typing import Optional


BASE_URL = "http://localhost:8001"
CHAIN_NAME = "flux-to-qwen-edit"
CHAINS_DIR = Path(__file__).parent / "chains"


def load_chain_definition(chain_name: str) -> dict:
    """Load chain definition YAML file"""
    chain_file = CHAINS_DIR / f"{chain_name}.yaml"
    if not chain_file.exists():
        raise FileNotFoundError(f"Chain definition not found: {chain_file}")
    with open(chain_file) as f:
        return yaml.safe_load(f)


def get_step_parameters(chain_def: dict, step_id: str) -> dict:
    """Get parameters for a specific step from chain definition"""
    for step in chain_def.get('steps', []):
        if step.get('id') == step_id:
            return step.get('parameters', {})
    return {}


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


def prompt_for_parameters(step_id: str, current_params: dict) -> dict:
    """Interactively prompt user to override parameters"""
    print(f"\n   Current parameters for step '{step_id}':")
    print("   " + "-" * 50)

    param_list = list(current_params.items())
    for i, (key, value) in enumerate(param_list):
        print(f"   [{i}] {key}: {value}")

    print("\n   Enter parameter overrides (empty line to finish):")
    print("   Format: <number or key> = <new_value>")
    print("   Example: 0 = new prompt text")
    print("            6.text = My new prompt")

    new_params = {}
    while True:
        try:
            user_input = input("   > ").strip()
        except EOFError:
            break

        if not user_input:
            break

        if "=" not in user_input:
            print("   Invalid format. Use: <key> = <value>")
            continue

        key_part, value_part = user_input.split("=", 1)
        key_part = key_part.strip()
        value_part = value_part.strip()

        # Handle numeric index
        if key_part.isdigit():
            idx = int(key_part)
            if 0 <= idx < len(param_list):
                key_part = param_list[idx][0]
            else:
                print(f"   Invalid index. Use 0-{len(param_list)-1}")
                continue

        # Try to parse value as JSON, otherwise keep as string
        try:
            parsed_value = json.loads(value_part)
        except json.JSONDecodeError:
            parsed_value = value_part

        new_params[key_part] = parsed_value
        print(f"   Set {key_part} = {parsed_value}")

    return new_params


async def interactive_approval(client: httpx.AsyncClient, approval: dict, chain_def: dict) -> bool:
    """Handle approval interactively - returns True if approved, False if rejected"""
    token = approval['approval_link_token']
    step_id = approval.get('step_id', 'unknown')
    artifact_url = approval.get('artifact_view_url', 'No URL available')

    print(f"\n   {'=' * 60}")
    print(f"   APPROVAL REQUEST: {step_id}")
    print(f"   {'=' * 60}")
    print(f"   Artifact URL: {artifact_url}")
    print(f"   Step ID: {step_id}")
    print(f"   Chain: {approval.get('chain_name', 'unknown')}")
    print(f"   {'=' * 60}")

    while True:
        try:
            choice = input("\n   Approve this step? (y/n): ").strip().lower()
        except EOFError:
            choice = 'y'

        if choice in ('y', 'yes'):
            response = await approve_request(client, token)
            if response.status_code == 200:
                print(f"   ✅ Step '{step_id}' APPROVED")
                return True
            else:
                print(f"   ❌ Approval failed: {response.status_code} - {response.text}")
                return False

        elif choice in ('n', 'no'):
            # Get current parameters from chain definition
            current_params = get_step_parameters(chain_def, step_id)
            if not current_params:
                print(f"   No parameters found for step '{step_id}' in chain definition")
                current_params = {}

            new_params = prompt_for_parameters(step_id, current_params)

            if not new_params:
                print("   No parameters changed. Please provide at least one parameter override.")
                continue

            comment = input("   Rejection comment (optional): ").strip()

            response = await reject_request(client, token, new_params, comment=comment)
            if response.status_code == 200:
                print(f"   🔄 Step '{step_id}' REJECTED - will regenerate with new parameters")
                return False
            else:
                print(f"   ❌ Rejection failed: {response.status_code} - {response.text}")
                return False
        else:
            print("   Please enter 'y' or 'n'")


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
# TEST: Flux Dev to Qwen Image Edit Chain Execution
# ============================================================================

async def test_flux_to_qwen_chain():
    """
    Interactive test for Flux Dev to Qwen Image Edit chain execution

    This test:
    - Executes the flux-to-qwen-edit chain
    - Step 1: generate_image (Flux Dev) - generates base image
    - Step 2: qwen_edit - edits generated image with local reference image
    - Shows artifact URLs for each approval step
    - Allows user to approve (y) or reject (n) with parameter overrides
    """

    print("\n" + "=" * 70)
    print("INTERACTIVE TEST: FLUX DEV TO QWEN IMAGE EDIT CHAIN")
    print("=" * 70)

    # Load chain definition for parameter reference
    print("\n1. Loading chain definition...")
    try:
        chain_def = load_chain_definition(CHAIN_NAME)
        print(f"   ✓ Chain definition loaded: {chain_def.get('name', CHAIN_NAME)}")
    except FileNotFoundError as e:
        print(f"   ❌ {e}")
        return False

    async with httpx.AsyncClient(timeout=1800.0) as client:
        # Start chain execution
        print("\n2. Starting chain execution...")
        response = await client.post(
            f"{BASE_URL}/chains/{CHAIN_NAME}/execute",
            json={"parameters": {}}
        )

        if response.status_code != 200:
            print(f"   ❌ Chain start failed: {response.status_code} - {response.text}")
            return False

        exec_result = response.json()
        workflow_id = exec_result['workflow_id']
        print(f"   ✓ Chain started: {workflow_id}")
        print(f"   Chain name: {exec_result['chain_name']}")
        print(f"   Total steps: {exec_result['total_steps']}")

        # Handle approvals interactively
        print("\n3. Interactive approval flow...")
        approved_count = 0
        rejected_count = 0

        for i in range(10):  # Safety limit (allow for regenerations)
            approval = await wait_for_approval(client, timeout=600)
            if not approval:
                print("   No more approvals pending")
                break

            was_approved = await interactive_approval(client, approval, chain_def)
            if was_approved:
                approved_count += 1
            else:
                rejected_count += 1

        print(f"\n   Summary: {approved_count} approved, {rejected_count} rejected")

        # Wait for chain completion
        print("\n4. Waiting for chain completion...")
        final_status = await monitor_chain_completion(client, workflow_id)

        if not final_status:
            print("   ❌ Chain did not complete in time")
            return False

        # Get final result
        print("\n5. Getting chain result...")
        response = await client.get(f"{BASE_URL}/chains/result/{workflow_id}")
        if response.status_code != 200:
            print(f"   ❌ ERROR: {response.status_code}")
            return False

        result = response.json()
        print(f"   Status: {result['status']}")
        print(f"   Successful Steps: {result['successful_steps']}")

        # Verify execution
        print("\n6. Verifying execution flow...")
        print(f"   Steps: generate_image → qwen_edit")
        print(f"   Local input: reference_image (uploaded to ComfyUI)")
        print(f"\n   Final step statuses:")

        for step_id, step_result in result['step_results'].items():
            status = step_result.get('status', 'unknown')
            output = step_result.get('output', {})
            output_info = f" → {output.get('image', 'no output')}" if output else ""
            print(f"   {step_id}: {status}{output_info}")

        success = result['status'] == 'completed'
        print(f"\n   {'✓ TEST PASSED' if success else '❌ TEST FAILED'}")
        return success


# ============================================================================
# Main Test Runner
# ============================================================================

async def run_test():
    """Run the interactive Flux to Qwen chain test"""

    print("\n" + "=" * 70)
    print("INTERACTIVE CHAIN EXECUTION TEST")
    print("=" * 70)
    print(f"Chain: {CHAIN_NAME}")
    print(f"Base URL: {BASE_URL}")
    print("Mode: Interactive (approve/reject with parameter overrides)")
    print("=" * 70)

    try:
        success = await test_flux_to_qwen_chain()

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
