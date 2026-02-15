"""Manifest loader and validator for agent packages."""

import re
from pathlib import Path
from typing import Any

import yaml


REQUIRED_FIELDS = ["name", "version", "description", "runtime", "entrypoint"]
VALID_RUNTIMES = ["python"]
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load a manifest.yaml file from disk."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path) as f:
        manifest = yaml.safe_load(f)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a YAML mapping")
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Validate a manifest dict. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    if "runtime" in manifest and manifest["runtime"] not in VALID_RUNTIMES:
        errors.append(f"Invalid runtime: {manifest['runtime']}. Must be one of: {VALID_RUNTIMES}")

    if "version" in manifest and not SEMVER_PATTERN.match(str(manifest["version"])):
        errors.append(f"Invalid version format: {manifest['version']}. Must be semver (e.g., 1.0.0)")

    if "input_schema" in manifest and not isinstance(manifest["input_schema"], dict):
        errors.append("input_schema must be a JSON Schema object")

    if "tags" in manifest and not isinstance(manifest["tags"], list):
        errors.append("tags must be a list of strings")

    if "price_per_call_cents" in manifest:
        price = manifest["price_per_call_cents"]
        if not isinstance(price, int) or price < 0:
            errors.append("price_per_call_cents must be a non-negative integer")

    return errors
