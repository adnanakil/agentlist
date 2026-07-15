"""Live location is scoped to one turn and redacted before persistence."""

from types import SimpleNamespace

from hal_orchestrator.routes.message import (
    MessageRequest,
    _live_location_guard_applies,
    _requires_live_location,
    _sanitize_persisted_history,
    _stable_message_payload,
)
from hal_orchestrator.tools.places import tool_places
from hal_orchestrator.tools.plugins.current_location import tool_current_location


async def test_current_location_tool_uses_only_context_location() -> None:
    ctx = SimpleNamespace(
        current_location={
            "label": "123 Example Street, Example City",
            "updated": "Now",
            "observed_at": "2026-07-15T18:00:00+00:00",
            "approximate": True,
        }
    )
    result = await tool_current_location({}, ctx)

    assert "123 Example Street" in result
    assert "approximate" in result
    assert "do not repeat the precise address" in result


async def test_current_location_tool_never_substitutes_home() -> None:
    result = await tool_current_location({}, SimpleNamespace(current_location=None))
    assert "unavailable" in result
    assert "Do not assume the user is at home" in result


def test_live_location_does_not_change_idempotency_payload() -> None:
    base = {
        "message_id": "message-1",
        "phone": "+1555",
        "text": "what is near me?",
    }
    first = MessageRequest(
        **base,
        current_location={
            "label": "First place",
            "observed_at": "2026-07-15T18:00:00Z",
        },
    )
    second = MessageRequest(
        **base,
        current_location={
            "label": "Second place",
            "observed_at": "2026-07-15T18:01:00Z",
        },
    )
    assert _stable_message_payload(first) == _stable_message_payload(second)


def test_live_location_is_scrubbed_from_persisted_tool_call_args() -> None:
    address = "123 Example Street, Example City"
    history = [
        {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "name": "places",
                        "args": {"query": f"ramen near {address.lower()}"},
                    }
                }
            ],
        }
    ]
    cleaned = _sanitize_persisted_history(history, live_location_label=address)
    assert address.lower() not in str(cleaned).lower()
    assert "[live location expired]" in str(cleaned)
    # The call shape survives so the transcript still shows a places call.
    assert cleaned[0]["parts"][0]["functionCall"]["name"] == "places"


def test_live_location_is_redacted_from_saved_history() -> None:
    address = "123 Example Street, Example City"
    history = [
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "current_location",
                        "response": {"content": f"Current location: {address}"},
                    }
                }
            ],
        }
    ]
    cleaned = _sanitize_persisted_history(history)
    assert address not in str(cleaned)
    assert "expired" in str(cleaned)


class _PlacesResponse:
    status_code = 200
    content = b""
    headers: dict = {}

    @staticmethod
    def json() -> dict:
        return {"places": []}


class _PlacesClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def post(self, _url: str, **kwargs) -> _PlacesResponse:
        self.requests.append(kwargs)
        return _PlacesResponse()


async def test_places_forces_find_my_location_over_model_guess() -> None:
    client = _PlacesClient()
    ctx = SimpleNamespace(
        settings=SimpleNamespace(google_maps_api_key="test-key"),
        current_location={"label": "123 Example Street, Example City"},
        user_text="What's a good restaurant near me right now?",
        http_client=client,
        result_images=[],
    )

    result = await tool_places(
        {
            "query": "best restaurants near Chelsea",
            "open_now": True,
            "max_results": 3,
        },
        ctx,
    )

    sent_query = client.requests[0]["json"]["textQuery"]
    assert "123 Example Street, Example City" in sent_query
    assert "Chelsea" not in sent_query
    assert "shared location" in result


async def test_places_refuses_to_guess_when_live_location_is_missing() -> None:
    client = _PlacesClient()
    ctx = SimpleNamespace(
        settings=SimpleNamespace(google_maps_api_key="test-key"),
        current_location=None,
        user_text="Find coffee near me",
        http_client=client,
        result_images=[],
    )

    result = await tool_places({"query": "coffee in Chelsea"}, ctx)

    assert not client.requests
    assert "live location is unavailable" in result
    assert "Do not guess" in result


def test_live_location_request_detection_covers_user_phrasing() -> None:
    assert _requires_live_location("Are there good coffee shops around me?")
    assert _requires_live_location("What's open near me right now?")
    assert _requires_live_location("Directions from here")
    assert _requires_live_location("What's the closest pharmacy to me?")
    assert not _requires_live_location("Find coffee in Greenpoint")
    # An explicit anchor means the user gave their own origin — forcing the
    # live label onto it would override what they actually asked for.
    assert not _requires_live_location("What's the closest subway to Times Square?")


def test_live_location_guard_skips_unaddressed_group_chatter() -> None:
    # DM without a location: hard stop before the model runs.
    assert _live_location_guard_applies(
        internal=False, is_group=False, text="any good bars nearby?", has_location=False
    )
    # Group members talking to each other must not summon a canned reply —
    # that would bypass the group mute and tact gates.
    assert not _live_location_guard_applies(
        internal=False, is_group=True, text="any good bars nearby?", has_location=False
    )
    # Explicitly addressing HAL in a group keeps the deterministic guard.
    assert _live_location_guard_applies(
        internal=False,
        is_group=True,
        text="Hal, any good bars nearby?",
        has_location=False,
    )
    # A validated location or an internal turn never triggers the guard.
    assert not _live_location_guard_applies(
        internal=False, is_group=False, text="any good bars nearby?", has_location=True
    )
    assert not _live_location_guard_applies(
        internal=True, is_group=False, text="any good bars nearby?", has_location=False
    )


async def test_places_query_uses_only_the_asking_clause() -> None:
    client = _PlacesClient()
    ctx = SimpleNamespace(
        settings=SimpleNamespace(google_maps_api_key="test-key"),
        current_location={"label": "123 Example Street, Example City"},
        user_text="I'm starving. What's a good ramen spot near me? We're meeting Sarah at 8.",
        http_client=client,
        result_images=[],
    )

    await tool_places({"query": "ramen"}, ctx)

    sent_query = client.requests[0]["json"]["textQuery"]
    assert "123 Example Street, Example City" in sent_query
    assert "ramen spot" in sent_query
    assert "Sarah" not in sent_query
    assert "starving" not in sent_query
