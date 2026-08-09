"""POST /api/outbox/enqueue — bridge-auth-protected durable enqueue."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

import hal_orchestrator.state as state
from ag_db.session import get_session
from hal_orchestrator.routes.message import build_message_router

SECRET = "test-bridge-secret"
PHONE = "+15551234567"


def _app(fake_session: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(build_message_router())

    async def _override_session():
        yield fake_session

    app.dependency_overrides[get_session] = _override_session
    return app


def _fake_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=uuid.uuid4())
        )
    )
    session.commit = AsyncMock()
    return session


@pytest.fixture
def bridge_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(state.settings, "hal_bridge_secret", SECRET)
    yield
    monkeypatch.undo()


async def test_enqueue_authorized_enqueues_message(bridge_secret) -> None:
    session = _fake_session()
    transport = httpx.ASGITransport(app=_app(session))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/outbox/enqueue",
            headers={"Authorization": f"Bearer {SECRET}"},
            json={
                "phone": PHONE,
                "text": "🎬 TikTok finds for you:\nfunny\nhttps://www.tiktok.com/@x/video/1",
                "channel": "whatsapp",
            },
        )

    assert response.status_code == 200
    assert response.json()["id"]

    # The durable outbox insert went through the caller's session with the
    # phone as destination and the requested channel.
    stmt = session.execute.call_args.args[0]
    params = stmt.compile().params
    assert params["destination"] == PHONE
    assert params["channel"] == "whatsapp"
    assert "TikTok finds" in params["text"]
    session.commit.assert_awaited_once()


async def test_enqueue_rejects_wrong_bearer(bridge_secret) -> None:
    session = _fake_session()
    transport = httpx.ASGITransport(app=_app(session))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/outbox/enqueue",
            headers={"Authorization": "Bearer nope"},
            json={"phone": PHONE, "text": "hi", "channel": "whatsapp"},
        )

    assert response.status_code == 401
    session.execute.assert_not_called()


async def test_enqueue_rejects_missing_bearer(bridge_secret) -> None:
    session = _fake_session()
    transport = httpx.ASGITransport(app=_app(session))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/outbox/enqueue",
            json={"phone": PHONE, "text": "hi", "channel": "whatsapp"},
        )

    # FastAPI rejects a missing required Authorization header before the
    # dependency runs.
    assert response.status_code == 422
    session.execute.assert_not_called()


async def test_enqueue_rejects_unknown_channel(bridge_secret) -> None:
    session = _fake_session()
    transport = httpx.ASGITransport(app=_app(session))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/outbox/enqueue",
            headers={"Authorization": f"Bearer {SECRET}"},
            json={"phone": PHONE, "text": "hi", "channel": "pigeon"},
        )

    assert response.status_code == 400
    session.execute.assert_not_called()
