#!/usr/bin/env python3
"""
Test script for ComfyUI Resource Registry

This script tests the resource discovery against real ComfyUI servers
configured in config.yaml.

Usage:
    cd /home/jaskirat/Documents/comfyautomate
    python scripts/test_resource_registry.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from scripts.comfyui_resource_registry import (
    ComfyUIResourceRegistry,
    ComfyUIResourceClient,
    WorkflowDependencyAnalyzer,
    ResourceType,
    SyncStatus,
)
from core.config import get_servers


async def test_single_server(server_config: dict):
    """Test resource discovery on a single server."""
    name = server_config.get("name")
    address = server_config.get("address")
    port = server_config.get("port")  # None if not specified

    # Build URL
    if address.startswith(("http://", "https://")):
        url = address
    elif port:
        url = f"http://{address}:{port}"
    else:
        url = f"http://{address}"

    print(f"\n{'='*60}")
    print(f"Testing Server: {name}")
    print(f"URL: {url}")
    print("="*60)

    client = ComfyUIResourceClient(name, url)

    try:
        inventory = await client.discover_all()

        if inventory.sync_status == SyncStatus.SYNCED:
            print(f"✓ Sync successful!")
            print(f"\nResources discovered:")

            # Group by type
            for resource_type in ResourceType:
                resources = inventory.get_resources_by_type(resource_type)
                if resources:
                    print(f"\n  {resource_type.value.upper()} ({len(resources)}):")
                    for r in resources[:5]:  # Show first 5
                        print(f"    - {r.relative_path}")
                    if len(resources) > 5:
                        print(f"    ... and {len(resources) - 5} more")

            # Show templates
            if inventory.workflow_templates:
                print(f"\n  WORKFLOW TEMPLATES ({len(inventory.workflow_templates)}):")
                for t in list(inventory.workflow_templates.values())[:5]:
                    print(f"    - {t.name} ({t.content_hash[:8]})")
        else:
            print(f"✗ Sync failed: {inventory.error_message}")

        return inventory

    except Exception as e:
        print(f"✗ Error: {e}")
        return None


async def test_registry_with_all_servers():
    """Test the full registry with all configured servers."""
    servers = get_servers()

    print("\n" + "="*60)
    print("ComfyUI Resource Registry Test")
    print(f"Found {len(servers)} server(s) in config.yaml")
    print("="*60)

    # Create registry
    registry = ComfyUIResourceRegistry(
        storage_path=Path("./data/comfyui_registry.json")
    )

    # Register and sync each server
    for server_config in servers:
        name = server_config.get("name")
        address = server_config.get("address")
        port = server_config.get("port")

        if address.startswith(("http://", "https://")):
            url = address
        elif port:
            url = f"http://{address}:{port}"
        else:
            url = f"http://{address}"

        try:
            await registry.register_server(name, url, auto_sync=True)
        except Exception as e:
            print(f"Failed to register {name}: {e}")

    # Summary
    print("\n" + "="*60)
    print("Registry Summary")
    print("="*60)

    for name, inventory in registry.servers.items():
        stats = inventory.to_dict()['stats']
        status = "✓" if inventory.sync_status == SyncStatus.SYNCED else "✗"
        print(f"\n{status} {name}:")
        print(f"   Nodes:       {stats['available_nodes']}")
        print(f"   Checkpoints: {stats['checkpoints']}")
        print(f"   LoRAs:       {stats['loras']}")
        print(f"   VAEs:        {stats['vaes']}")
        print(f"   Embeddings:  {stats['embeddings']}")
        print(f"   ControlNets: {stats['controlnets']}")
        print(f"   Templates:   {stats['workflow_templates']}")

    # Test workflow analysis
    print("\n" + "="*60)
    print("Testing Workflow Dependency Analysis")
    print("="*60)

    # Load a sample workflow from templates
    templates_dir = project_root / "core" / "templates"
    if templates_dir.exists():
        workflow_files = list(templates_dir.glob("*.json"))
        if workflow_files:
            import json
            sample_file = workflow_files[0]
            print(f"\nAnalyzing: {sample_file.name}")

            with open(sample_file) as f:
                workflow = json.load(f)

            analyzer = WorkflowDependencyAnalyzer()
            deps = analyzer.analyze(workflow)

            if deps:
                print("Dependencies found:")
                for resource_type, paths in deps.items():
                    for path in paths:
                        print(f"  [{resource_type.value}] {path}")

                # Check if resources are available
                for server_name in registry.servers.keys():
                    result = analyzer.validate_workflow_on_server(
                        workflow, registry, server_name
                    )
                    if result['valid']:
                        print(f"\n✓ Workflow can run on {server_name}")
                    else:
                        print(f"\n✗ Workflow missing resources on {server_name}:")
                        for rtype, missing in result['missing'].items():
                            for m in missing:
                                print(f"    [{rtype}] {m}")
            else:
                print("No external resource dependencies found")

    return registry


async def test_api_endpoints():
    """Test raw ComfyUI API endpoints for resource discovery."""
    servers = get_servers()

    if not servers:
        print("No servers configured in config.yaml")
        return

    server = servers[0]
    name = server.get("name")
    address = server.get("address")
    port = server.get("port")

    if address.startswith(("http://", "https://")):
        base_url = address
    elif port:
        base_url = f"http://{address}:{port}"
    else:
        base_url = f"http://{address}"

    print(f"\nTesting raw API endpoints on {name} ({base_url})")
    print("="*60)

    import aiohttp

    endpoints = [
        "/system_stats",
        "/object_info",
        "/embeddings",
        "/models/checkpoints",
        "/models/loras",
        "/models/vae",
        "/api/userdata/workflows",
        "/api/templates",
    ]

    async with aiohttp.ClientSession() as session:
        for endpoint in endpoints:
            url = f"{base_url}{endpoint}"
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    status = resp.status
                    if status == 200:
                        data = await resp.json()
                        if isinstance(data, list):
                            count = len(data)
                        elif isinstance(data, dict):
                            count = len(data)
                        else:
                            count = 1
                        print(f"  ✓ {endpoint}: {status} ({count} items)")
                    else:
                        print(f"  ✗ {endpoint}: {status}")
            except asyncio.TimeoutError:
                print(f"  ✗ {endpoint}: timeout")
            except aiohttp.ClientConnectorError:
                print(f"  ✗ {endpoint}: connection error")
            except Exception as e:
                print(f"  ✗ {endpoint}: {type(e).__name__}: {e}")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("ComfyUI Resource Registry - Integration Test")
    print("="*60)

    # Test 1: Raw API endpoints
    await test_api_endpoints()

    # Test 2: Single server discovery
    servers = get_servers()
    if servers:
        await test_single_server(servers[0])

    # Test 3: Full registry
    registry = await test_registry_with_all_servers()

    print("\n" + "="*60)
    print("Tests Complete!")
    print("="*60)

    if registry:
        summary = registry.to_dict()['summary']
        print(f"\nFinal Summary:")
        print(f"  Servers: {summary['total_servers']}")
        print(f"  Resources: {summary['total_resources']}")
        print(f"  Templates: {summary['total_templates']}")

        # Save to disk
        print(f"\nRegistry saved to: ./data/comfyui_registry.json")


if __name__ == "__main__":
    asyncio.run(main())
