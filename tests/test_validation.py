"""Tests for manifest validation."""

from agentgate_sdk.manifest import validate_manifest


def test_valid_manifest():
    manifest = {
        "name": "test-agent",
        "version": "1.0.0",
        "description": "A test agent",
        "runtime": "python",
        "entrypoint": "agent.py",
    }
    errors = validate_manifest(manifest)
    assert errors == []


def test_missing_required_fields():
    manifest = {"name": "test"}
    errors = validate_manifest(manifest)
    assert len(errors) >= 4  # missing version, description, runtime, entrypoint


def test_invalid_runtime():
    manifest = {
        "name": "test",
        "version": "1.0.0",
        "description": "test",
        "runtime": "node",
        "entrypoint": "index.js",
    }
    errors = validate_manifest(manifest)
    assert any("runtime" in e.lower() or "node" in e.lower() for e in errors)


def test_invalid_version():
    manifest = {
        "name": "test",
        "version": "not-semver",
        "description": "test",
        "runtime": "python",
        "entrypoint": "agent.py",
    }
    errors = validate_manifest(manifest)
    assert any("version" in e.lower() for e in errors)


def test_valid_semver_with_prerelease():
    manifest = {
        "name": "test",
        "version": "1.0.0-beta.1",
        "description": "test",
        "runtime": "python",
        "entrypoint": "agent.py",
    }
    errors = validate_manifest(manifest)
    assert errors == []


def test_invalid_tags():
    manifest = {
        "name": "test",
        "version": "1.0.0",
        "description": "test",
        "runtime": "python",
        "entrypoint": "agent.py",
        "tags": "not-a-list",
    }
    errors = validate_manifest(manifest)
    assert any("tags" in e.lower() for e in errors)


def test_negative_price():
    manifest = {
        "name": "test",
        "version": "1.0.0",
        "description": "test",
        "runtime": "python",
        "entrypoint": "agent.py",
        "price_per_call_cents": -5,
    }
    errors = validate_manifest(manifest)
    assert any("price" in e.lower() for e in errors)
