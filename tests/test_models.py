"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from ag_common.models import (
    CreateAccountRequest,
    DepositRequest,
    DiscoverRequest,
    InvokeRequest,
)


class TestCreateAccountRequest:
    def test_valid(self):
        req = CreateAccountRequest(email="test@example.com", password="password123")
        assert req.email == "test@example.com"
        assert req.role.value == "consumer"

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            CreateAccountRequest(email="not-an-email", password="password123")

    def test_short_password(self):
        with pytest.raises(ValidationError):
            CreateAccountRequest(email="test@example.com", password="short")


class TestDepositRequest:
    def test_valid(self):
        req = DepositRequest(amount_cents=1000)
        assert req.amount_cents == 1000

    def test_too_small(self):
        with pytest.raises(ValidationError):
            DepositRequest(amount_cents=50)  # min is 100

    def test_too_large(self):
        with pytest.raises(ValidationError):
            DepositRequest(amount_cents=2_000_000)  # max is 1_000_000


class TestDiscoverRequest:
    def test_valid(self):
        req = DiscoverRequest(query="scrape a website")
        assert req.limit == 10

    def test_empty_query(self):
        with pytest.raises(ValidationError):
            DiscoverRequest(query="")

    def test_custom_limit(self):
        req = DiscoverRequest(query="test", limit=5, category="web")
        assert req.limit == 5
        assert req.category == "web"


class TestInvokeRequest:
    def test_with_agent_id(self):
        req = InvokeRequest(
            agent_id="12345678-1234-1234-1234-123456789012",
            input={"message": "hello"},
        )
        assert req.input == {"message": "hello"}

    def test_with_agent_slug(self):
        req = InvokeRequest(agent_slug="echo", input={"message": "hello"})
        assert req.agent_slug == "echo"
