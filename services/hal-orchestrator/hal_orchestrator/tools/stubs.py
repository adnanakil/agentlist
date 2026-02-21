"""Stub tools — return "not yet available" for deferred functionality."""

from __future__ import annotations

STUB_MESSAGE = (
    "This tool ({name}) is not yet available in the cloud version of HAL. "
    "It will be migrated in a future update."
)


def tool_stub(name: str) -> str:
    """Return a stub response for tools not yet implemented in cloud."""
    return STUB_MESSAGE.format(name=name)
