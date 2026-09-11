from __future__ import annotations

import pytest

from app import auth
from app.config import Settings


class _URL:
    path = "/v1/payments/intents"


class _State:
    principal = {"sub": "user-17"}


class _Request:
    method = "POST"
    url = _URL()
    state = _State()
    headers = {"Idempotency-Key": "idem-production-17"}


def _settings():
    return Settings(environment="production", authz_gate_url="https://authz.invalid/decision")


@pytest.mark.asyncio
async def test_production_resource_grant_is_audit_chained_before_action(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings())

    async def allowed(*args, **kwargs):
        return {"allow": True, "decision_id": "authz-resource-17", "engines": ["openfga", "opa"]}

    captured = {}

    def audit(event_type, target_id, data, **kwargs):
        captured.update(event_type=event_type, target_id=target_id, data=data)
        return "audit-1"

    monkeypatch.setattr(auth, "_authorize", allowed)
    monkeypatch.setattr(auth, "append_audit", audit)

    resource = {
        "type": "payment_intent",
        "action": "create",
        "merchant_id": "mrc_17",
        "destination_account_id": "acct_17",
        "amount_minor": 125,
        "currency": "USD",
        "rail": "ecocash",
    }
    decision = await auth.authorize_resource(_Request(), resource)

    assert decision["decision_id"] == "authz-resource-17"
    assert captured["event_type"] == "authorization.resource_granted"
    assert captured["target_id"] == "idempotency:idem-production-17"
    assert captured["data"]["actor"] == "user-17"
    assert captured["data"]["authorization_decision_id"] == "authz-resource-17"
    assert captured["data"]["idempotency_key"] == "idem-production-17"
    assert captured["data"]["resource"] == resource


@pytest.mark.asyncio
async def test_authorized_action_fails_closed_if_audit_attribution_cannot_persist(monkeypatch):
    monkeypatch.setattr(auth, "settings", _settings())

    async def allowed(*args, **kwargs):
        return {"allow": True, "decision_id": "authz-resource-18", "engines": ["openfga", "opa"]}

    def broken_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(auth, "_authorize", allowed)
    monkeypatch.setattr(auth, "append_audit", broken_audit)

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await auth.authorize_resource(
            _Request(),
            {"type": "payment_intent", "action": "create", "merchant_id": "mrc_18"},
        )
