import asyncio
import importlib

import pytest

from app.rails.base import RailResult


def _reload_for_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "fabric.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as db
    import app.audit as audit
    import app.ledger as ledger
    import app.service as service
    for mod in (config, db, audit, ledger, service):
        importlib.reload(mod)
    db.init_db()
    return service


@pytest.mark.asyncio
async def test_idempotency_key_reuse_with_different_request_is_rejected(tmp_path, monkeypatch):
    service = _reload_for_db(tmp_path, monkeypatch)
    merchant = service.create_merchant("Merchant", "USD")
    account = merchant["settlement_account"]["id"]

    first = await service.create_payment_intent(
        merchant_id=merchant["id"],
        destination_account_id=account,
        amount_minor=100,
        currency="USD",
        rail="internal",
        payer_ref="payer",
        description="first",
        idempotency_key="idem-conflict",
    )
    assert first["amount_minor"] == 100

    with pytest.raises(service.PaymentError, match="idempotency"):
        await service.create_payment_intent(
            merchant_id=merchant["id"],
            destination_account_id=account,
            amount_minor=200,
            currency="USD",
            rail="internal",
            payer_ref="payer",
            description="different",
            idempotency_key="idem-conflict",
        )


@pytest.mark.asyncio
async def test_concurrent_idempotent_requests_reach_rail_only_once(tmp_path, monkeypatch):
    service = _reload_for_db(tmp_path, monkeypatch)
    merchant = service.create_merchant("Merchant", "USD")
    account = merchant["settlement_account"]["id"]

    class YieldingRail:
        def __init__(self):
            self.calls = 0

        async def create_payment(self, request):
            self.calls += 1
            await asyncio.sleep(0.05)
            return RailResult(
                external_reference=request.payment_id,
                status="pending",
                raw={"mode": "test"},
            )

    rail = YieldingRail()
    service.RAILS["internal"] = rail

    kwargs = dict(
        merchant_id=merchant["id"],
        destination_account_id=account,
        amount_minor=100,
        currency="USD",
        rail="internal",
        payer_ref="payer",
        description="same",
        idempotency_key="idem-concurrent",
    )
    results = await asyncio.gather(
        service.create_payment_intent(**kwargs),
        service.create_payment_intent(**kwargs),
        return_exceptions=True,
    )

    assert rail.calls == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
