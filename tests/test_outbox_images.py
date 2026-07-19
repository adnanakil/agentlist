"""Images ride the durable outbox so proactive sends can attach cards."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from hal_orchestrator.services import cron as cron_svc
from hal_orchestrator.services.delivery import claim, enqueue

PNG_IMAGE = {"mime_type": "image/png", "data": "cGln", "ext": "png"}


async def test_enqueue_stores_images_on_row() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value="id"))
    )

    await enqueue(session, to="+1555", text="digest", images=[PNG_IMAGE])

    stmt = session.execute.call_args.args[0]
    assert stmt.compile().params["images"] == [PNG_IMAGE]


async def test_enqueue_without_images_stores_null() -> None:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value="id"))
    )

    await enqueue(session, to="+1555", text="digest")

    stmt = session.execute.call_args.args[0]
    assert stmt.compile().params["images"] is None


def _claim_session(rows: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    return session


async def test_claim_returns_images() -> None:
    row = SimpleNamespace(
        id="7f0b", destination="chat123", text="digest", images=[PNG_IMAGE],
        attempts=0, status="pending", delivered_at=None, lease_until=None,
    )
    bare = SimpleNamespace(
        id="7f0c", destination="+1555", text="plain", images=None,
        attempts=0, status="pending", delivered_at=None, lease_until=None,
    )

    messages = await claim(_claim_session([row, bare]))

    assert messages[0]["images"] == [PNG_IMAGE]
    assert messages[1]["images"] == []


async def test_cron_forwards_result_images_to_enqueue() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "reply": "🌙 Bazzy today: 3 naps",
        "side_messages": [{"to": "+1666", "text": "side note"}],
        "result_images": [
            {**PNG_IMAGE, "_source": "baby_status_card"},
            {"mime_type": "", "data": "junk", "ext": "png"},
        ],
    }
    http = SimpleNamespace(post=AsyncMock(return_value=response))
    job = SimpleNamespace(
        id="j1", phone="+1555", sender_phone=None, prompt="/baby-digest",
        is_group=True, chat_id="chat123", next_run_at=datetime.now(UTC),
    )
    settings = SimpleNamespace(hal_bridge_secret="secret")

    with patch(
        "hal_orchestrator.services.delivery.enqueue", new=AsyncMock()
    ) as mock_enqueue:
        await cron_svc._run_job(settings, http, job, session=object())

    reply_call = mock_enqueue.call_args_list[0]
    assert reply_call.kwargs["to"] == "chat123"
    assert reply_call.kwargs["images"] == [PNG_IMAGE]

    side_call = mock_enqueue.call_args_list[1]
    assert side_call.kwargs["text"] == "side note"
    assert "images" not in side_call.kwargs
