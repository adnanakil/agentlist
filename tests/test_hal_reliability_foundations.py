"""Fast contract tests for HAL's reliability and extension boundaries."""

import asyncio
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from hal_orchestrator import main
from hal_orchestrator.middleware.request_size import ContentLengthLimitMiddleware
from hal_orchestrator.routes.message import ImageData, MessageRequest
from hal_orchestrator.services.action_policy import _explicit_send_request, arguments_hash
from hal_orchestrator.services.baby_card import card_url, verify_card_token
from hal_orchestrator.services.idempotency import begin, internal_message_id
from hal_orchestrator.tools.specs import all_tool_specs, model_tools


def test_tool_registry_is_single_source_for_model_declarations() -> None:
    specs = all_tool_specs()
    declarations = model_tools()[0]["function_declarations"]
    assert {spec.name for spec in specs} == {item["name"] for item in declarations}
    assert len(specs) == len({spec.name for spec in specs})


def test_send_authorization_uses_actual_inbound_text_and_target() -> None:
    assert _explicit_send_request("Text my wife that I'm late", {"to": "wife"})
    assert _explicit_send_request("send +12015550123 hello", {"to": "+12015550123"})
    assert not _explicit_send_request("Summarize this page", {"to": "+12015550123"})
    assert not _explicit_send_request("Text my wife", {"to": "unknown person"})


def test_confirmation_hash_ignores_only_the_server_token() -> None:
    base = {"to": "wife", "text": "Running late"}
    assert arguments_hash(base) == arguments_hash({**base, "confirmation_token": "abc"})
    assert arguments_hash(base) != arguments_hash({**base, "text": "Send money"})


def test_internal_message_ids_are_stable_and_purpose_bound() -> None:
    first = internal_message_id("heartbeat", "+1555", "check weather")
    assert first == internal_message_id("heartbeat", "+1555", "check weather")
    assert first != internal_message_id("followup", "+1555", "check weather")


def test_card_tokens_expire() -> None:
    url = card_url("https://hal.example", "+1555", "card-secret", ttl_seconds=60)
    query = parse_qs(urlparse(url).query)
    expires = int(query["e"][0])
    assert verify_card_token(query["s"][0], query["sig"][0], expires, "card-secret") == "+1555"
    with patch("hal_orchestrator.services.baby_card.time.time", return_value=expires + 1):
        assert verify_card_token(
            query["s"][0], query["sig"][0], expires, "card-secret"
        ) is None


def test_message_contract_bounds_images_and_text() -> None:
    with pytest.raises(ValidationError):
        MessageRequest(phone="+1555", text="x" * 12001)
    with pytest.raises(ValidationError):
        ImageData(mime_type="text/html", data="abc")
    with pytest.raises(ValidationError):
        MessageRequest(
            phone="+1555",
            text="images",
            images=[ImageData(mime_type="image/png", data="a")] * 5,
        )


def test_worker_set_cancels_siblings_when_one_loop_stops(monkeypatch) -> None:
    async def scenario() -> None:
        sibling_cancelled = asyncio.Event()

        async def stops() -> None:
            return

        async def waits() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        monkeypatch.setattr(
            main,
            "_worker_coroutines",
            lambda _settings, _client: (stops(), waits()),
        )
        await asyncio.wait_for(main._run_worker_set(object(), object()), timeout=1)
        assert sibling_cancelled.is_set()

    asyncio.run(scenario())


def test_request_size_limit_counts_chunked_body_without_content_length() -> None:
    async def scenario() -> None:
        chunks = iter(
            [
                {"type": "http.request", "body": b"1234", "more_body": True},
                {"type": "http.request", "body": b"5678", "more_body": False},
            ]
        )
        sent: list[dict] = []

        async def receive() -> dict:
            return next(chunks)

        async def send(message: dict) -> None:
            sent.append(message)

        async def app(_scope, wrapped_receive, _send) -> None:
            while (await wrapped_receive()).get("more_body"):
                pass

        middleware = ContentLengthLimitMiddleware(app, max_bytes=6)
        await middleware(
            {"type": "http", "headers": []},
            receive,
            send,
        )
        assert sent[0]["status"] == 413

    asyncio.run(scenario())


def test_completed_idempotency_response_is_copied_before_rollback() -> None:
    class Event:
        silo = "+1555"
        status = "completed"

        def __init__(self, session, digest) -> None:
            self.session = session
            self.payload_hash = digest

        @property
        def response(self) -> dict:
            if self.session.rolled_back:
                raise RuntimeError("expired ORM attribute")
            return {"reply": "stored", "tool_calls": 0}

    class InsertResult:
        def scalar_one_or_none(self):
            return None

    class SelectResult:
        def __init__(self, event) -> None:
            self.event = event

        def scalar_one(self):
            return self.event

    class Session:
        def __init__(self) -> None:
            self.rolled_back = False
            self.calls = 0

        async def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return InsertResult()
            from hal_orchestrator.services.idempotency import payload_hash

            return SelectResult(Event(self, payload_hash({"text": "hello"})))

        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            self.rolled_back = True

    async def scenario() -> None:
        session = Session()
        response = await begin(
            session,
            message_id="message-1",
            silo="+1555",
            payload={"text": "hello"},
        )
        assert response == {"reply": "stored", "tool_calls": 0}
        assert session.rolled_back

    asyncio.run(scenario())
