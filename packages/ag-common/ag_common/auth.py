"""API key generation and validation utilities."""

import hashlib
import secrets


API_KEY_PREFIX = "ag_live_"
API_KEY_BYTES = 32


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (full_key, key_prefix, key_hash).
        full_key is returned to the user once and never stored.
        key_hash (SHA-256 hex) is stored in the database.
    """
    random_part = secrets.token_urlsafe(API_KEY_BYTES)
    full_key = f"{API_KEY_PREFIX}{random_part}"
    key_prefix = full_key[:12]
    key_hash = hash_api_key(full_key)
    return full_key, key_prefix, key_hash


def hash_api_key(key: str) -> str:
    """SHA-256 hash of an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()
