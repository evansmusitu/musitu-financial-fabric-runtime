from __future__ import annotations

import pytest

from app.config import Settings
from app.rails import ecocash as ecocash_module
from app.rails.base import RailRequest


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self):
        self.payment_payload = None
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, path, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _Response({"access_token": "provider-token"})
        self.payment_payload = kwargs.get("json")
        return _Response({"reference": "provider-ref-1", "status": "pending"})


def _cfg(callback_url: str) -> Settings:
    return Settings(
        environment="production",
        ecocash_contract_confirmed=True,
        ecocash_contract_version="contract-v1",
        ecocash_api_base="https://ecocash.invalid",
        ecocash_oauth_path="/oauth/token",
        ecocash_payment_path="/payments",
        ecocash_callback_url=callback_url,
        ecocash_client_id="client",
        ecocash_client_secret="secret",
    )


@pytest.mark.asyncio
async def test_production_provider_callback_cannot_be_redirected_by_caller(monkeypatch):
    configured_callback = "https://musitu.example/v1/webhooks/ecocash"
    cfg = _cfg(configured_callback)
    client = _Client()
    monkeypatch.setattr(ecocash_module, "settings", cfg)
    monkeypatch.setattr(ecocash_module, "assert_live_funds_allowed", lambda: None)
    monkeypatch.setattr(ecocash_module.httpx, "AsyncClient", lambda *args, **kwargs: client)

    result = await ecocash_module.EcoCashRail().create_payment(RailRequest(
        payment_id="pay_test",
        amount_minor=100,
        currency="USD",
        payer_ref="payer",
        description="test",
        callback_url="https://attacker.invalid/divert-provider-status",
    ))

    assert result.external_reference == "provider-ref-1"
    assert client.payment_payload is not None
    assert client.payment_payload["callback_url"] == configured_callback
    assert client.payment_payload["callback_url"] != "https://attacker.invalid/divert-provider-status"


@pytest.mark.asyncio
async def test_production_connector_rejects_missing_dedicated_callback(monkeypatch):
    cfg = _cfg("")
    monkeypatch.setattr(ecocash_module, "settings", cfg)
    monkeypatch.setattr(ecocash_module, "assert_live_funds_allowed", lambda: None)

    with pytest.raises(RuntimeError, match="configuration incomplete"):
        await ecocash_module.EcoCashRail().create_payment(RailRequest(
            payment_id="pay_test",
            amount_minor=100,
            currency="USD",
            payer_ref="payer",
            description="test",
            callback_url="https://merchant.invalid/callback",
        ))
