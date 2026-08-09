"""Everyday care events (medicine, poops, baths, play …) are logged as
structured kinds, surface in day/week summaries, and are searchable later
via baby(action=history)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from hal_orchestrator.services.baby import (
    AUX_KINDS,
    AWAKE_KINDS,
    EVENT_KINDS,
    SLEEP_STARTS,
    day_aux,
    format_day_aux,
)
from hal_orchestrator.tools.baby import tool_baby

ET = ZoneInfo("America/New_York")


def _et(h: int, mi: int, d: int = 18) -> datetime:
    return datetime(2026, 7, d, h, mi, tzinfo=ET).astimezone(UTC)


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        session=object(),
        phone="+1555",
        sender_phone="+1555",
        is_group=False,
        result_images=[],
    )


def _family() -> SimpleNamespace:
    return SimpleNamespace(
        baby_name="Bazzy",
        timezone="America/New_York",
        id="family",
        baby_birthdate=None,
        state={},
    )


def test_event_kinds_cover_everyday_care_and_fit_the_column() -> None:
    for kind in ("medicine", "bath", "play", "screen_time", "solids",
                 "symptom", "milestone", "diaper", "note"):
        assert kind in EVENT_KINDS
    for kind in EVENT_KINDS:
        assert len(kind) <= 16  # HalBabyEvent.kind is String(16)
    assert EVENT_KINDS - {"feed", "nap_start", "bedtime", "wake"} == AUX_KINDS
    assert SLEEP_STARTS.isdisjoint(AWAKE_KINDS)


def test_day_aux_filters_to_aux_kinds_on_the_day() -> None:
    events = [
        ("feed", _et(7, 0), ""),
        ("medicine", _et(15, 0), "Tylenol 2.5ml"),
        ("diaper", _et(9, 30), "poopy"),
        ("bath", _et(18, 15, d=17), ""),  # previous day — excluded
        ("nap_start", _et(12, 0), ""),
    ]
    aux = day_aux(events, ET, _et(12, 0).astimezone(ET).date())
    assert [(k, n) for k, _, n in aux] == [
        ("diaper", "poopy"), ("medicine", "Tylenol 2.5ml")
    ]


def test_format_day_aux_aggregates_diapers_and_lists_the_rest() -> None:
    aux = [
        ("diaper", _et(9, 30), "poopy"),
        ("diaper", _et(11, 0), "wet"),
        ("diaper", _et(14, 10), "dirty"),
        ("medicine", _et(15, 0), "Tylenol 2.5ml"),
        ("screen_time", _et(16, 0), "20 min Bluey"),
        ("bath", _et(18, 15), ""),
    ]
    out = format_day_aux(aux, ET)
    assert "Diapers: 3 (2 poopy)" in out
    assert "medicine 3:00 PM (Tylenol 2.5ml)" in out
    assert "screen time 4:00 PM (20 min Bluey)" in out
    assert "bath 6:15 PM" in out


def test_format_day_aux_empty_is_empty() -> None:
    assert format_day_aux([], ET) == ""


async def test_history_searches_the_full_log() -> None:
    matches = [
        SimpleNamespace(kind="medicine", event_at=_et(15, 0, d=6), note="Tylenol 2.5ml"),
        SimpleNamespace(kind="medicine", event_at=_et(15, 0), note="Tylenol 2.5ml"),
    ]
    search = AsyncMock(return_value=(matches, 2))
    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=_family()),
        ),
        patch("hal_orchestrator.tools.baby.search_events", new=search),
    ):
        reply = await tool_baby({"action": "history", "query": "tylenol"}, _context())

    assert search.await_args.kwargs["query"] == "tylenol"
    assert search.await_args.kwargs["since"] is None  # no days → full log
    assert "2 events" in reply
    assert "Tylenol 2.5ml" in reply
    assert "Sat Jul 18, 3:00 PM" in reply


async def test_history_unknown_kind_becomes_text_search() -> None:
    search = AsyncMock(return_value=([], 0))
    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=_family()),
        ),
        patch("hal_orchestrator.tools.baby.search_events", new=search),
    ):
        reply = await tool_baby({"action": "history", "kind": "haircut"}, _context())

    assert search.await_args.kwargs["kind"] is None
    assert search.await_args.kwargs["query"] == "haircut"
    assert "No events found" in reply
    assert "haircut" in reply


async def test_history_known_kind_reports_empty_scope() -> None:
    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=_family()),
        ),
        patch(
            "hal_orchestrator.tools.baby.search_events",
            new=AsyncMock(return_value=([], 0)),
        ),
    ):
        reply = await tool_baby(
            {"action": "history", "kind": "bath", "days": 7}, _context()
        )
    assert "No events found" in reply
    assert "kind=bath" in reply


async def test_log_unknown_kind_files_as_note() -> None:
    add = AsyncMock()
    family = _family()
    family.state = {"forecast_revealed": "done"}
    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=family),
        ),
        patch(
            "hal_orchestrator.tools.baby.event_trigger_stats",
            new=AsyncMock(return_value=(5, {"+1555"})),
        ),
        patch(
            "hal_orchestrator.tools.baby.infer_wake_if_napping",
            new=AsyncMock(return_value=None),
        ),
        patch("hal_orchestrator.tools.baby.add_event", new=add),
        patch("hal_orchestrator.tools.baby.load_events", new=AsyncMock(return_value=[])),
        patch("hal_orchestrator.tools.baby.forecast_next", return_value={}),
        patch("hal_orchestrator.tools.baby.format_forecast", return_value=""),
        patch(
            "hal_orchestrator.tools.baby.apply_auto_reminders",
            new=AsyncMock(return_value=[]),
        ),
    ):
        reply = await tool_baby(
            {"action": "log", "kind": "haircut", "note": "first trim"}, _context()
        )

    assert add.await_args.args[2] == "note"  # (session, family, kind, ...)
    assert add.await_args.kwargs["note"] == "haircut — first trim"
    assert "Logged: Bazzy haircut" in reply
    assert "stored as a note" in reply
    # A truly empty kind still errors — only real words get auto-filed.
    with patch(
        "hal_orchestrator.tools.baby.get_family_for_silo",
        new=AsyncMock(return_value=_family()),
    ):
        reply = await tool_baby({"action": "log"}, _context())
    assert reply.startswith("Error: kind must be one of")


async def test_stats_today_includes_aux_events() -> None:
    events_raw = [
        SimpleNamespace(kind="feed", event_at=_et(7, 0), note=""),
        SimpleNamespace(kind="diaper", event_at=_et(9, 30), note="poopy"),
        SimpleNamespace(kind="medicine", event_at=_et(15, 0), note="Tylenol 2.5ml"),
    ]
    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=_family()),
        ),
        patch(
            "hal_orchestrator.tools.baby.load_events",
            new=AsyncMock(return_value=events_raw),
        ),
        patch("hal_orchestrator.tools.baby.datetime") as dt,
    ):
        # "yesterday" relative to a now one day after the fixture events.
        dt.now.return_value = _et(19, 0, d=19)
        reply = await tool_baby({"action": "stats", "period": "yesterday"}, _context())

    assert "Diapers: 1 (1 poopy)" in reply
    assert "medicine 3:00 PM (Tylenol 2.5ml)" in reply
