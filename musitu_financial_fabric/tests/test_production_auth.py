from __future__ import annotations

import pytest

from app.auth import _authorize
from app.config import Settings


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload, *args, **kwargs):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return _Response(self.payload)


class _URL:
    path = "/v1/payments/intents"


class _Request:
    method = "POST"
    url = _URL()


def _settings():
    return Settings(environment="production", authz_gate_url="https://authz.invalid/decision")


@pytest.mark.asyncio
async def test_openfga_only_authorization_is_rejected(monkeypatch):
    monkeypatch.setattr("app.auth.settings", _settings())
    monkeypatch.setattr(
        "app.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _Client({"allow": True, "decision_id": "a-1", "engines": ["openfga"]}),
    )
    with pytest.raises(PermissionError, match="incomplete"):
        await _authorize({"sub": "user-1"}, _Request())


@pytest.mark.asyncio
async def test_openfga_and_opa_authorization_is_accepted(monkeypatch):
    monkeypatch.setattr("app.auth.settings", _settings())
    monkeypatch.setattr(
        "app.auth.httpx.AsyncClient",
        lambda *args, **kwargs: _Client({"allow": True, "decision_id": "a-2", "engines": ["openfga", "opa"]}),
    )
    decision = await _authorize({"sub": "user-1"}, _Request())
    assert decision["allow"] is True
    assert decision["decision_id"] == "a-2"
