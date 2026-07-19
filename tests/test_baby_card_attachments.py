"""Baby status cards are sent as image attachments, not link previews."""

import base64
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from hal_orchestrator.services.baby import Sleep
from hal_orchestrator.services.baby_card import build_day_summary_data
from hal_orchestrator.tools.baby import tool_baby

ET = ZoneInfo("America/New_York")


def _et(h: int, mi: int) -> datetime:
    return datetime(2026, 7, 18, h, mi, tzinfo=ET).astimezone(UTC)


def _context(result_images: list[dict] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        session=object(),
        phone="+1555",
        sender_phone="+1555",
        result_images=result_images or [],
    )


async def test_explicit_card_is_attached_as_png() -> None:
    png = b"\x89PNG\r\n\x1a\ncard"
    family = SimpleNamespace(baby_name="Bazzy", timezone="America/New_York")
    ctx = _context()

    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=family),
        ),
        patch(
            "hal_orchestrator.services.baby_card.render_for_silo",
            new=AsyncMock(return_value=png),
        ),
    ):
        reply = await tool_baby({"action": "card"}, ctx)

    assert "attached as an image" in reply
    assert "http" not in reply
    assert len(ctx.result_images) == 1
    assert ctx.result_images[0]["mime_type"] == "image/png"
    assert ctx.result_images[0]["ext"] == "png"
    assert base64.b64decode(ctx.result_images[0]["data"]) == png


async def test_log_attaches_latest_card_without_discarding_other_images() -> None:
    png = b"\x89PNG\r\n\x1a\nlatest"
    family = SimpleNamespace(baby_name="Bazzy", timezone="America/New_York", id="family")
    unrelated = {"mime_type": "image/jpeg", "data": "photo", "ext": "jpg"}
    stale_card = {
        "mime_type": "image/png",
        "data": "stale",
        "ext": "png",
        "_source": "baby_status_card",
    }
    ctx = _context([unrelated, stale_card])

    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=family),
        ),
        patch("hal_orchestrator.tools.baby.add_event", new=AsyncMock()),
        patch("hal_orchestrator.tools.baby.load_events", new=AsyncMock(return_value=[])),
        patch("hal_orchestrator.tools.baby.as_pairs", return_value=[]),
        patch("hal_orchestrator.tools.baby.forecast_next", return_value={}),
        patch(
            "hal_orchestrator.tools.baby.apply_auto_reminders",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "hal_orchestrator.services.baby_card.render_for_silo",
            new=AsyncMock(return_value=png),
        ),
    ):
        reply = await tool_baby({"action": "log", "kind": "feed"}, ctx)

    assert "attached as an image" in reply
    assert "http" not in reply
    assert ctx.result_images[0] is unrelated
    assert len(ctx.result_images) == 2
    assert base64.b64decode(ctx.result_images[1]["data"]) == png


async def test_day_card_attaches_without_clobbering_status_card() -> None:
    png = b"\x89PNG\r\n\x1a\nday"
    family = SimpleNamespace(baby_name="Bazzy", timezone="America/New_York", id="family")
    status_card = {
        "mime_type": "image/png",
        "data": "status",
        "ext": "png",
        "_source": "baby_status_card",
    }
    ctx = _context([status_card])
    summary = {
        "date": date(2026, 7, 18),
        "feeds": [_et(7, 0)],
        "naps": [Sleep(start=_et(9, 25), end=_et(10, 3), is_night=False)],
        "bedtime": None,
        "morning_wake": _et(6, 40),
        "night_minutes": 645,
        "total_nap_minutes": 38,
    }

    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=family),
        ),
        patch("hal_orchestrator.tools.baby.load_events", new=AsyncMock(return_value=[])),
        patch("hal_orchestrator.tools.baby.as_pairs", return_value=[]),
        patch("hal_orchestrator.tools.baby.summarize_day", return_value=summary),
        patch(
            "hal_orchestrator.services.baby_card.render_day_summary_png",
            return_value=png,
        ),
    ):
        reply = await tool_baby({"action": "day_card"}, ctx)

    assert "day summary card is attached" in reply
    assert "http" not in reply
    assert ctx.result_images[0] is status_card
    assert len(ctx.result_images) == 2
    assert ctx.result_images[1]["_source"] == "baby_day_card"
    assert base64.b64decode(ctx.result_images[1]["data"]) == png


async def test_day_card_empty_day_attaches_nothing() -> None:
    family = SimpleNamespace(baby_name="Bazzy", timezone="America/New_York", id="family")
    ctx = _context()
    empty = {
        "date": date(2026, 7, 18),
        "feeds": [],
        "naps": [],
        "bedtime": None,
        "morning_wake": None,
        "night_minutes": None,
        "total_nap_minutes": 0,
    }

    with (
        patch(
            "hal_orchestrator.tools.baby.get_family_for_silo",
            new=AsyncMock(return_value=family),
        ),
        patch("hal_orchestrator.tools.baby.load_events", new=AsyncMock(return_value=[])),
        patch("hal_orchestrator.tools.baby.as_pairs", return_value=[]),
        patch("hal_orchestrator.tools.baby.summarize_day", return_value=empty),
    ):
        reply = await tool_baby({"action": "day_card"}, ctx)

    assert "Nothing logged yet today" in reply
    assert ctx.result_images == []


def test_build_day_summary_data_shapes_times_and_durations() -> None:
    summary = {
        "date": date(2026, 7, 18),
        "feeds": [_et(7, 0), _et(10, 5), _et(13, 5), _et(16, 45), _et(19, 0)],
        "naps": [
            Sleep(start=_et(9, 25), end=_et(10, 3), is_night=False),
            Sleep(start=_et(12, 13), end=_et(12, 50), is_night=False),
            Sleep(start=_et(15, 28), end=None, is_night=False),
        ],
        "bedtime": _et(19, 25),
        "morning_wake": _et(6, 40),
        "night_minutes": 645,
        "total_nap_minutes": 75,
    }
    now = _et(19, 55)

    data = build_day_summary_data(summary, "Bazzy", ET, now)

    assert data["baby"] == "Bazzy"
    assert data["date_label"] == "Saturday, July 18"
    assert data["morning_wake"] == "6:40 AM"
    assert data["night_duration"] == "10h 45m"
    assert data["naps"] == [
        {"start": "9:25 AM", "duration": "38m"},
        {"start": "12:13 PM", "duration": "37m"},
        {"start": "3:28 PM", "duration": "ongoing"},
    ]
    assert data["total_nap"] == "1h 15m"
    assert data["feeds"] == ["7:00 AM", "10:05 AM", "1:05 PM", "4:45 PM", "7:00 PM"]
    assert data["feed_count"] == 5
    assert data["bedtime"] == "7:25 PM"


def test_build_day_summary_data_empty_day() -> None:
    summary = {
        "date": date(2026, 7, 18),
        "feeds": [],
        "naps": [],
        "bedtime": None,
        "morning_wake": None,
        "night_minutes": None,
        "total_nap_minutes": 0,
    }
    data = build_day_summary_data(summary, "Bazzy", ET, _et(9, 0))

    assert data["morning_wake"] is None
    assert data["night_duration"] is None
    assert data["naps"] == []
    assert data["total_nap"] is None
    assert data["feeds"] == []
    assert data["feed_count"] == 0
    assert data["bedtime"] is None

