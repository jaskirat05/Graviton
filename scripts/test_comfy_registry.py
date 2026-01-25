#!/usr/bin/env python3
"""Test script for ComfyServerRegistry"""

import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.registry import ComfyServerRegistry


async def main():
    print("Testing ComfyServerRegistry...")

    # Get registry instance
    registry = ComfyServerRegistry.get_instance()

    print(f"\nLocal template hashes loaded: {len(registry.local_template_hashes)}")
    for hash_val, filename in list(registry.local_template_hashes.items())[:5]:
        print(f"  {filename}: {hash_val[:16]}...")

    print("\nSyncing all servers...")
    servers = await registry.sync_all_servers()

    for name, inventory in servers.items():
        print(f"\n=== {name} ===")
        print(f"  URL: {inventory.server_url}")
        print(f"  Nodes: {len(inventory.available_nodes)}")
        print(f"  Templates: {len(inventory.templates)}")

        if inventory.templates:
            print(f"  Template files: {inventory.templates[:5]}")

        if inventory.sync_error:
            print(f"  ERROR: {inventory.sync_error}")
        else:
            print(f"  Last sync: {inventory.last_sync}")

        # Test combo options (e.g., checkpoint loader)
        if 'CheckpointLoaderSimple' in inventory.available_nodes:
            options = inventory.get_combo_options('CheckpointLoaderSimple', 'ckpt_name')
            if options:
                print(f"  Available checkpoints: {len(options)}")
                for opt in options[:3]:
                    print(f"    - {opt}")

    print(f"\nLocal templates after sync: {len(registry.local_template_hashes)}")


if __name__ == "__main__":
    asyncio.run(main())
