from __future__ import annotations

import pytest

from app import auth
from app.config import Settings


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _CapturingClient:
    def __init__(self, response_payload):
        self.response_payload = response_payload
        self.sent_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        self.sent_json = kwargs.get("json")
        return _Response(self.response_payload)


class _URL:
    path = "/v1/payments/intents"


class _State:
    pass


class _Request:
    method = "POST"
    url = _URL()

    def __init__(self, principal=None):
        self.state = _State()
        if principal is not None:
            self.state.principal = principal


def _settings(environment="production"):
    return Settings(environment=environment, authz_gate_url="https://authz.invalid/decision")


@pytest.mark.asyncio
async def test_resource_context_is_sent_to_openfga_opa_gate(monkeypatch):
    client = _CapturingClient({"allow": True, "decision_id": "resource-1", "engines": ["openfga", "opa"]})
    monkeypatch.setattr(auth, "settings", _settings())
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: client)

    resource = {
        "type": "payment_intent",
        "action": "create",
        "merchant_id": "mrc_1",
        "destination_account_id": "acct_1",
        "amount_minor": 125,
        "currency": "USD",
        "rail": "ecocash",
    }
    decision = await auth._authorize({"sub": "user-1"}, _Request(), resource=resource)

    assert decision["decision_id"] == "resource-1"
    assert client.sent_json is not None
    assert client.sent_json["subject"] == "user-1"
    assert client.sent_json["method"] == "POST"
    assert client.sent_json["path"] == "/v1/payments/intents"
    assert client.sent_json["resource"] == resource
    assert client.sent_json["required_engines"] == ["openfga", "opa"]


@pytest.mark.asyncio
async def test_resource_authorization_still_requires_both_engines(monkeypatch):
    client = _CapturingClient({"allow": True, "decision_id": "resource-2", "engines": ["openfga"]})
    monkeypatch.setattr(auth, "settings", _settings())
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *args, **kwargs: client)

    with pytest.raises(PermissionError, match="incomplete"):
        await auth._authorize(
            {"sub": "user-1"},
            _Request(),
            resource={"type": "account", "id": "acct_1", "action": "read"},
        )


@pytest.mark.asyncio
async def test_authorize_resource_requires_authenticated_production_principal(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings())
    with pytest.raises(PermissionError, match="principal"):
        await auth.authorize_resource(
            _Request(),
            {"type": "payment", "id": "pay_1", "action": "read"},
        )


@pytest.mark.asyncio
async def test_authorize_resource_sandbox_does_not_call_external_gate(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings(environment="sandbox"))

    class _ShouldNotBeCalled:
        def __init__(self, *args, **kwargs):
            raise AssertionError("sandbox resource authorization must not call the external gate")

    monkeypatch.setattr(auth.httpx, "AsyncClient", _ShouldNotBeCalled)
    decision = await auth.authorize_resource(
        _Request(),
        {"type": "account", "id": "acct_1", "action": "read"},
    )
    assert decision["allow"] is True
    assert decision["decision_id"] == "sandbox"
