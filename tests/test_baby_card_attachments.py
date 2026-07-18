"""Baby status cards are sent as image attachments, not link previews."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hal_orchestrator.tools.baby import tool_baby


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

