"""Single runtime registry for HAL tools.

Legacy declarations are imported once from ``prompts.tool_defs``. New tools can
register one ``ToolSpec`` containing their declaration, handler, policy, and
runtime limits without modifying the central dispatcher.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Literal

ToolRisk = Literal["read", "write", "irreversible"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    declaration: dict
    handler: str
    scopes: frozenset[str] = frozenset({"dm", "group"})
    risk: ToolRisk = "read"
    timeout_seconds: int | None = None
    parallel_safe: bool = False


_HANDLERS = {
    "delegate": "hal_orchestrator.tools.delegate:tool_delegate",
    "current_time": "hal_orchestrator.tools.current_time:tool_current_time",
    "memory": "hal_orchestrator.tools.memory:tool_memory",
    "baby": "hal_orchestrator.tools.baby:tool_baby",
    "get_weather": "hal_orchestrator.tools.weather:tool_weather",
    "sports_score": "hal_orchestrator.tools.sports_score:tool_sports_score",
    "watch": "hal_orchestrator.tools.watch:tool_watch",
    "travel_time": "hal_orchestrator.tools.travel_time:tool_travel_time",
    "places": "hal_orchestrator.tools.places:tool_places",
    "profile": "hal_orchestrator.tools.profile:tool_profile",
    "web_search": "hal_orchestrator.tools.web_search:tool_web_search",
    "web_fetch": "hal_orchestrator.tools.web_search:tool_web_fetch",
    "send_message": "hal_orchestrator.tools.send_message:tool_send_message",
    "contacts": "hal_orchestrator.tools.contacts:tool_contacts",
    "set_reminder": "hal_orchestrator.tools.reminders:tool_set_reminder",
    "nyc_events": "hal_orchestrator.tools.nyc_events:tool_nyc_events",
    "parking": "hal_orchestrator.tools.parking:tool_parking",
    "group_quiet": "hal_orchestrator.tools.group_quiet:tool_group_quiet",
    "helpful_mode": "hal_orchestrator.tools.helpful:tool_helpful",
    "recall_history": "hal_orchestrator.tools.history:tool_recall_history",
    "schedule": "hal_orchestrator.tools.cron:tool_schedule",
    "browser": "hal_orchestrator.tools.browser:tool_browser",
    "image_edit": "hal_orchestrator.tools.image_edit:tool_image_edit",
    "trip": "hal_orchestrator.tools.trips:tool_trip",
    "google_auth": "hal_orchestrator.tools.google:tool_google_auth",
    "google_calendar": "hal_orchestrator.tools.google:tool_google_calendar",
    "google_gmail": "hal_orchestrator.tools.google:tool_google_gmail",
    "resy": "hal_orchestrator.tools.resy:tool_resy",
    "skill": "hal_orchestrator.tools.skill:tool_skill",
}

_DM_ONLY = {
    "send_message",
    "contacts",
    "helpful_mode",
    "google_auth",
    "google_calendar",
    "google_gmail",
}
_WRITE = {
    "memory",
    "baby",
    "watch",
    "profile",
    "contacts",
    "set_reminder",
    "group_quiet",
    "helpful_mode",
    "schedule",
    "image_edit",
    "trip",
    "google_auth",
    "google_calendar",
    "skill",
}
_PARALLEL = {
    "web_search",
    "web_fetch",
    "get_weather",
    "travel_time",
    "sports_score",
    "places",
}

_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(spec: ToolSpec) -> None:
    if spec.name in _REGISTRY:
        raise ValueError(f"duplicate HAL tool: {spec.name}")
    if spec.declaration.get("name") != spec.name:
        raise ValueError(f"tool declaration name mismatch: {spec.name}")
    _REGISTRY[spec.name] = spec


def _register_legacy_tools() -> None:
    from hal_orchestrator.prompts.tool_defs import MAIN_TOOLS

    declarations = MAIN_TOOLS[0]["function_declarations"]
    declared = {d["name"] for d in declarations}
    missing = declared - _HANDLERS.keys()
    extra = _HANDLERS.keys() - declared
    if missing or extra:
        raise RuntimeError(
            f"HAL tool registry drift; missing handlers={sorted(missing)}, "
            f"missing declarations={sorted(extra)}"
        )
    for declaration in declarations:
        name = declaration["name"]
        register_tool(
            ToolSpec(
                name=name,
                declaration=declaration,
                handler=_HANDLERS[name],
                scopes=frozenset({"dm"}) if name in _DM_ONLY else frozenset({"dm", "group"}),
                risk="irreversible" if name == "send_message" else ("write" if name in _WRITE else "read"),
                parallel_safe=name in _PARALLEL,
            )
        )


_register_legacy_tools()


def _load_plugins() -> None:
    """Import drop-in modules under tools/plugins; each registers one spec."""
    from hal_orchestrator.tools import plugins

    for module in pkgutil.iter_modules(plugins.__path__, f"{plugins.__name__}."):
        importlib.import_module(module.name)


_load_plugins()


def get_tool_spec(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def all_tool_specs() -> tuple[ToolSpec, ...]:
    return tuple(_REGISTRY.values())


def model_tools(names: list[str] | None = None) -> list[dict]:
    allowed = set(names) if names is not None else None
    declarations = [
        spec.declaration
        for spec in _REGISTRY.values()
        if allowed is None or spec.name in allowed
    ]
    return [{"function_declarations": declarations}] if declarations else []
