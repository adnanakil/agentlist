"""Manifest validation for agent submissions."""

import re

SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

REQUIRED_FIELDS = ["name", "version", "description", "runtime", "entrypoint"]


def validate_manifest(manifest: dict) -> list[str]:
    """Validate an agent manifest dictionary.

    Checks:
      - All required fields are present and non-empty.
      - Runtime is "python".
      - Version matches the semver specification.

    Args:
        manifest: The manifest dictionary to validate.

    Returns:
        A list of validation error strings. An empty list means the manifest is valid.
    """
    errors: list[str] = []

    # Check required fields
    for field in REQUIRED_FIELDS:
        value = manifest.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"Missing required manifest field: {field}")

    # Check runtime value
    runtime = manifest.get("runtime")
    if runtime is not None and runtime != "python":
        errors.append(f"Unsupported runtime '{runtime}'; only 'python' is allowed")

    # Check version format
    version = manifest.get("version")
    if version is not None and isinstance(version, str) and version.strip():
        if not SEMVER_PATTERN.match(version):
            errors.append(
                f"Invalid version '{version}'; must follow semantic versioning (e.g. 1.0.0)"
            )

    return errors
