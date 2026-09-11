from __future__ import annotations

import pytest

from app import audit, db, policy, service
from app.config import Settings
from app.rails.base import RailResult
from app.risk import RiskDecision


def _production_cfg(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "dispatch.db"),
        environment="production",
        live_funds_enabled=False,
        production_mode="shadow",
        production_enabled_rails=("ecocash",),
        production_enabled_currencies=("USD",),
        ecocash_contract_confirmed=True,
        ecocash_contract_version="test-contract-v1",
        ecocash_api_base="https://ecocash.invalid",
        ecocash_oauth_path="/oauth/token",
        ecocash_payment_path="/payments",
        ecocash_client_id="test-client",
        ecocash_client_secret="test-secret",
    )


def _prepare(tmp_path, monkeypatch):
    cfg = _production_cfg(tmp_path)
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(audit, "settings", cfg)
    monkeypatch.setattr(policy, "settings", cfg)
    monkeypatch.setattr(service, "settings", cfg)
    monkeypatch.setattr(
        service,
        "evaluate_reference_risk",
        lambda **_: RiskDecision(True, 7, "allow", "risk-decision-1"),
    )
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
            ("mrc_prod", "Production Merchant", "active", "2026-09-11T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,?,?)",
            ("acct_prod", "merchant", "mrc_prod", "USD", "settlement", "active", "2026-09-11T00:00:00+00:00"),
        )
    return cfg


async def _create(key: str):
    return await service.create_payment_intent(
        merchant_id="mrc_prod",
        destination_account_id="acct_prod",
        amount_minor=125,
        currency="USD",
        rail="ecocash",
        payer_ref="payer-1",
        description="production dispatch test",
        idempotency_key=key,
        callback_url="https://merchant.invalid/callback",
    )


@pytest.mark.asyncio
async def test_provider_timeout_becomes_ambiguous_and_is_never_blindly_retried(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    class TimeoutRail:
        def __init__(self):
            self.calls = 0

        async def create_payment(self, request):
            self.calls += 1
            raise TimeoutError("test-only timeout")

    rail = TimeoutRail()
    monkeypatch.setitem(service.RAILS, "ecocash", rail)

    first = await _create("production-timeout-1")
    assert first["status"] == "provider_ambiguous"
    assert first["reconciliation_required"] is True
    assert first["automatic_retry_allowed"] is False
    assert rail.calls == 1

    second = await _create("production-timeout-1")
    assert second["id"] == first["id"]
    assert second["status"] == "provider_ambiguous"
    assert second["reconciliation_required"] is True
    assert rail.calls == 1, "idempotent retry must never re-dispatch an ambiguous provider operation"

    with db.connect() as conn:
        idem = conn.execute(
            "SELECT status,payment_id FROM payment_idempotency WHERE idempotency_key=?",
            ("production-timeout-1",),
        ).fetchone()
    assert idem["status"] == "committed"
    assert idem["payment_id"] == first["id"]

    reconciliation = service.reconcile()
    assert reconciliation["provider_attention_required"] == 1
    assert reconciliation["provider_attention"][0]["id"] == first["id"]


@pytest.mark.asyncio
async def test_provider_response_does_not_mark_money_succeeded_before_authenticated_settlement(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    class SuccessRail:
        def __init__(self):
            self.calls = 0

        async def create_payment(self, request):
            self.calls += 1
            return RailResult(
                external_reference="provider-reference-123",
                status="succeeded",
                raw={"status": "succeeded"},
            )

    rail = SuccessRail()
    monkeypatch.setitem(service.RAILS, "ecocash", rail)

    first = await _create("production-provider-success-1")
    assert first["status"] == "pending"
    assert first["external_reference"] == "provider-reference-123"
    assert first["provider_initial_status"] == "succeeded"
    assert first["reconciliation_required"] is False
    assert rail.calls == 1

    second = await _create("production-provider-success-1")
    assert second["id"] == first["id"]
    assert second["status"] == "pending"
    assert rail.calls == 1


@pytest.mark.asyncio
async def test_dispatch_is_durably_committed_before_external_effect(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    observed = {}

    class InspectingRail:
        async def create_payment(self, request):
            with db.connect() as conn:
                payment = conn.execute("SELECT * FROM payment_intents WHERE id=?", (request.payment_id,)).fetchone()
                idem = conn.execute(
                    "SELECT status,payment_id FROM payment_idempotency WHERE idempotency_key=?",
                    ("production-ordering-1",),
                ).fetchone()
            observed["payment_status"] = payment["status"] if payment else None
            observed["idem_status"] = idem["status"] if idem else None
            observed["idem_payment_id"] = idem["payment_id"] if idem else None
            return RailResult("provider-ordering-1", "pending", {})

    monkeypatch.setitem(service.RAILS, "ecocash", InspectingRail())
    payment = await _create("production-ordering-1")

    assert observed == {
        "payment_status": "dispatching",
        "idem_status": "committed",
        "idem_payment_id": payment["id"],
    }
    assert payment["status"] == "pending"
