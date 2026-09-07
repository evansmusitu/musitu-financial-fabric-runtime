import importlib

import pytest


def _reload_for_db(tmp_path, monkeypatch, *, environment="sandbox"):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "fabric.db"))
    monkeypatch.setenv("MUSITU_ENV", environment)
    import app.config as config
    import app.db as db
    import app.audit as audit
    import app.ledger as ledger
    import app.service as service
    for mod in (config, db, audit, ledger, service):
        importlib.reload(mod)
    db.init_db()
    return db, service


@pytest.mark.asyncio
async def test_pending_review_merchant_cannot_create_production_payment(tmp_path, monkeypatch):
    _, service = _reload_for_db(tmp_path, monkeypatch, environment="production")
    merchant = service.create_merchant("Merchant", "USD")
    assert merchant["status"] == "pending_review"

    with pytest.raises(service.PaymentError, match="merchant.*approved|approved.*merchant"):
        await service.create_payment_intent(
            merchant_id=merchant["id"],
            destination_account_id=merchant["settlement_account"]["id"],
            amount_minor=100,
            currency="USD",
            rail="internal",
            payer_ref="payer",
            description="must not bypass review",
            idempotency_key="pending-review-1",
        )


@pytest.mark.asyncio
async def test_inactive_destination_account_cannot_accept_new_payment(tmp_path, monkeypatch):
    db, service = _reload_for_db(tmp_path, monkeypatch)
    merchant = service.create_merchant("Merchant", "USD")
    account_id = merchant["settlement_account"]["id"]
    with db.connect() as conn:
        conn.execute("UPDATE accounts SET status='suspended' WHERE id=?", (account_id,))

    with pytest.raises(service.PaymentError, match="account.*active|active.*account"):
        await service.create_payment_intent(
            merchant_id=merchant["id"],
            destination_account_id=account_id,
            amount_minor=100,
            currency="USD",
            rail="internal",
            payer_ref="payer",
            description="suspended destination",
            idempotency_key="suspended-account-1",
        )
