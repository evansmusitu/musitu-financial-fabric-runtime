from __future__ import annotations

import importlib


def _reload_policy(monkeypatch, *, environment="production", enabled_rails="ecocash", enabled_currencies="USD", contract="true", secret="secret"):
    monkeypatch.setenv("MUSITU_ENV", environment)
    monkeypatch.setenv("MUSITU_PRODUCTION_ENABLED_RAILS", enabled_rails)
    monkeypatch.setenv("MUSITU_PRODUCTION_ENABLED_CURRENCIES", enabled_currencies)
    monkeypatch.setenv("MUSITU_ECOCASH_CONTRACT_CONFIRMED", contract)
    monkeypatch.setenv("MUSITU_ECOCASH_CONTRACT_VERSION", "contract-v1")
    monkeypatch.setenv("MUSITU_ECOCASH_API_BASE", "https://ecocash.invalid")
    monkeypatch.setenv("MUSITU_ECOCASH_OAUTH_PATH", "/oauth/token")
    monkeypatch.setenv("MUSITU_ECOCASH_PAYMENT_PATH", "/payments")
    monkeypatch.setenv("MUSITU_ECOCASH_CLIENT_ID", "client")
    monkeypatch.setenv("MUSITU_ECOCASH_CLIENT_SECRET", secret)
    import app.config as config
    import app.policy as policy
    importlib.reload(config)
    importlib.reload(policy)
    return policy


def test_production_denies_currency_not_explicitly_enabled(monkeypatch):
    policy = _reload_policy(monkeypatch, enabled_currencies="USD")
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="EUR", rail="ecocash", max_amount_minor=1000)
    assert decision.allow is False
    assert decision.reason == "currency_not_production_enabled"


def test_production_denies_rail_not_explicitly_enabled(monkeypatch):
    policy = _reload_policy(monkeypatch, enabled_rails="ecocash")
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="USD", rail="bank", max_amount_minor=1000)
    assert decision.allow is False
    assert decision.reason == "rail_not_production_enabled"


def test_production_denies_enabled_but_unimplemented_connector(monkeypatch):
    policy = _reload_policy(monkeypatch, enabled_rails="bank")
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="USD", rail="bank", max_amount_minor=1000)
    assert decision.allow is False
    assert decision.reason == "production_connector_unavailable"


def test_production_denies_ecocash_before_contract_confirmation(monkeypatch):
    policy = _reload_policy(monkeypatch, contract="false")
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="USD", rail="ecocash", max_amount_minor=1000)
    assert decision.allow is False
    assert decision.reason == "ecocash_contract_unconfirmed"


def test_production_denies_incomplete_ecocash_connector(monkeypatch):
    policy = _reload_policy(monkeypatch, secret="")
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="USD", rail="ecocash", max_amount_minor=1000)
    assert decision.allow is False
    assert decision.reason == "ecocash_connector_incomplete"


def test_production_allows_fully_configured_implemented_rail(monkeypatch):
    policy = _reload_policy(monkeypatch)
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="USD", rail="ecocash", max_amount_minor=1000)
    assert decision.allow is True


def test_sandbox_behavior_remains_compatible(monkeypatch):
    policy = _reload_policy(monkeypatch, environment="sandbox", enabled_rails="", enabled_currencies="")
    decision = policy.evaluate_payment_policy(amount_minor=100, currency="USD", rail="bank", max_amount_minor=1000)
    assert decision.allow is True
