"""End-to-end test: create account -> deposit -> discover -> invoke -> check balance.

This test requires all services running (via docker-compose + make dev).
It tests the full consumer journey through the gateway API.
"""

import httpx
import pytest

GATEWAY_URL = "http://localhost:8000"

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.fixture
async def http_client():
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=30.0) as client:
        yield client


async def test_health(http_client: httpx.AsyncClient):
    """Verify the gateway is running."""
    resp = await http_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "gateway"


async def test_unauthenticated_request(http_client: httpx.AsyncClient):
    """Verify that unauthenticated requests are rejected."""
    resp = await http_client.get("/v1/balance")
    assert resp.status_code == 401


async def test_invalid_api_key(http_client: httpx.AsyncClient):
    """Verify that invalid API keys are rejected."""
    resp = await http_client.get(
        "/v1/balance",
        headers={"Authorization": "Bearer ag_live_invalidkey123"},
    )
    assert resp.status_code == 401


async def test_full_consumer_flow(http_client: httpx.AsyncClient):
    """Full E2E flow: balance -> discover -> invoke -> verify charges.

    NOTE: This test requires:
    1. All services running
    2. A pre-created test account with API key (from seed_db.py --with-test-data)
    3. At least one active agent seeded

    The test API key should be set via TEST_API_KEY env var.
    """
    import os

    api_key = os.environ.get("TEST_API_KEY")
    if not api_key:
        pytest.skip("TEST_API_KEY not set — skipping E2E test")

    headers = {"Authorization": f"Bearer {api_key}"}

    # 1. Check initial balance
    resp = await http_client.get("/v1/balance", headers=headers)
    assert resp.status_code == 200
    initial_balance = resp.json()["balance_cents"]

    # 2. Discover agents
    resp = await http_client.post(
        "/v1/discover",
        headers=headers,
        json={"query": "echo test agent", "limit": 5},
    )
    assert resp.status_code == 200
    agents = resp.json()["agents"]
    assert len(agents) > 0

    # 3. Invoke an agent (if we have balance)
    agent = agents[0]
    if initial_balance >= agent["price_per_call_cents"]:
        resp = await http_client.post(
            "/v1/invoke",
            headers=headers,
            json={
                "agent_slug": agent["slug"],
                "input": {"message": "hello from e2e test"},
            },
        )
        assert resp.status_code == 200
        invoke_data = resp.json()
        assert invoke_data["status"] in ("completed", "failed", "timeout")

        if invoke_data["status"] == "completed":
            # 4. Verify balance was deducted
            resp = await http_client.get("/v1/balance", headers=headers)
            assert resp.status_code == 200
            new_balance = resp.json()["balance_cents"]
            assert new_balance == initial_balance - agent["price_per_call_cents"]

    # 5. Check transaction history
    resp = await http_client.get("/v1/history", headers=headers)
    assert resp.status_code == 200
    assert "transactions" in resp.json()
