"""
Chain Definition Hashing

Provides content-addressable caching for chain definitions.
Same definition = same hash = can share cache.
"""

import hashlib
import json
from typing import Dict, Any


def calculate_definition_hash(chain_definition: Dict[str, Any]) -> str:
    """
    Calculate a stable hash of a chain definition.

    The hash is based on the normalized JSON representation,
    ensuring consistent hashing regardless of key ordering.

    Args:
        chain_definition: Chain definition dict (from YAML)

    Returns:
        16-character hex hash (first 16 chars of SHA256)
    """
    # Normalize: sort keys, remove whitespace variations
    normalized = json.dumps(chain_definition, sort_keys=True, separators=(',', ':'))

    # Calculate SHA256 and take first 16 chars (64 bits, collision-resistant enough)
    full_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return full_hash[:16]


def definitions_match(def1: Dict[str, Any], def2: Dict[str, Any]) -> bool:
    """
    Check if two chain definitions are equivalent.

    Args:
        def1: First chain definition
        def2: Second chain definition

    Returns:
        True if definitions produce the same hash
    """
    return calculate_definition_hash(def1) == calculate_definition_hash(def2)
