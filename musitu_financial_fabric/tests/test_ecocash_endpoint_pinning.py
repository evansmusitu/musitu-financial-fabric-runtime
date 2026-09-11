from __future__ import annotations

import pytest

from app.config import Settings
from app.rails import ecocash as ecocash_module
from app.rails.base import RailRequest


def _cfg(**overrides):
    values = dict(
        environment="production",
        ecocash_contract_confirmed=True,
        ecocash_contract_version="contract-v1",
        ecocash_api_base="https://provider.example",
        ecocash_oauth_path="/oauth/token",
        ecocash_payment_path="/payments",
        ecocash_callback_url="https://musitu.example/v1/webhooks/ecocash",
        ecocash_client_id="client",
        ecocash_client_secret="secret",
    )
    values.update(overrides)
    return Settings(**values)


def _request():
    return RailRequest(
        payment_id="pay_test",
        amount_minor=100,
        currency="USD",
        payer_ref="payer",
        description="test",
        callback_url=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ecocash_oauth_path", "https://attacker.invalid/oauth", "OAuth endpoint"),
        ("ecocash_oauth_path", "//attacker.invalid/oauth", "OAuth endpoint"),
        ("ecocash_payment_path", "https://attacker.invalid/payments", "payment endpoint"),
        ("ecocash_payment_path", "//attacker.invalid/payments", "payment endpoint"),
    ],
)
async def test_credential_bearing_ecocash_endpoints_cannot_escape_pinned_provider_host(monkeypatch, field, value, message):
    cfg = _cfg(**{field: value})
    monkeypatch.setattr(ecocash_module, "settings", cfg)
    monkeypatch.setattr(ecocash_module, "assert_live_funds_allowed", lambda: None)

    def should_not_create_client(*args, **kwargs):
        raise AssertionError("HTTP client must not be created for an unpinned endpoint")

    monkeypatch.setattr(ecocash_module.httpx, "AsyncClient", should_not_create_client)
    with pytest.raises(RuntimeError, match=message):
        await ecocash_module.EcoCashRail().create_payment(_request())


def test_normal_relative_provider_paths_are_accepted():
    assert ecocash_module._relative_provider_path("/oauth/token") is True
    assert ecocash_module._relative_provider_path("payments") is True
    assert ecocash_module._relative_provider_path("https://attacker.invalid/payments") is False
    assert ecocash_module._relative_provider_path("//attacker.invalid/payments") is False
