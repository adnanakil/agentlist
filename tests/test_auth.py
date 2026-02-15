"""Tests for API key generation and validation."""

from ag_common.auth import generate_api_key, hash_api_key, API_KEY_PREFIX


def test_generate_api_key_format():
    full_key, key_prefix, key_hash = generate_api_key()

    assert full_key.startswith(API_KEY_PREFIX)
    assert len(full_key) > 20
    assert key_prefix == full_key[:12]
    assert len(key_hash) == 64  # SHA-256 hex


def test_generate_api_key_uniqueness():
    keys = {generate_api_key()[0] for _ in range(100)}
    assert len(keys) == 100


def test_hash_api_key_consistency():
    key = "ag_live_testkey123"
    hash1 = hash_api_key(key)
    hash2 = hash_api_key(key)
    assert hash1 == hash2


def test_hash_api_key_different_keys():
    hash1 = hash_api_key("ag_live_key1")
    hash2 = hash_api_key("ag_live_key2")
    assert hash1 != hash2
