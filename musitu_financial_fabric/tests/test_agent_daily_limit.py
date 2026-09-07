import importlib

import pytest


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
async def test_agent_mandate_daily_limit_blocks_cumulative_overspend(tmp_path, monkeypatch):
    service = _reload_for_db(tmp_path, monkeypatch)
    principal = service.create_identity("human", "Principal")
    agent = service.create_identity("agent", "Agent")
    merchant = service.create_merchant("Merchant", "USD")
    mandate = service.create_agent_mandate(
        principal_id=principal["id"],
        agent_id=agent["id"],
        max_per_payment_minor=80,
        max_daily_minor=100,
        currency="USD",
        allowed_rails=["internal"],
    )

    first = await service.create_agent_payment(
        mandate_id=mandate["id"],
        merchant_id=merchant["id"],
        destination_account_id=merchant["settlement_account"]["id"],
        amount_minor=60,
        currency="USD",
        rail="internal",
        description="first",
        idempotency_key="agent-daily-1",
    )
    assert first["status"] == "pending"

    with pytest.raises(service.PaymentError, match="daily"):
        await service.create_agent_payment(
            mandate_id=mandate["id"],
            merchant_id=merchant["id"],
            destination_account_id=merchant["settlement_account"]["id"],
            amount_minor=60,
            currency="USD",
            rail="internal",
            description="second",
            idempotency_key="agent-daily-2",
        )


@pytest.mark.asyncio
async def test_agent_daily_limit_does_not_double_count_idempotent_retry(tmp_path, monkeypatch):
    service = _reload_for_db(tmp_path, monkeypatch)
    principal = service.create_identity("human", "Principal")
    agent = service.create_identity("agent", "Agent")
    merchant = service.create_merchant("Merchant", "USD")
    mandate = service.create_agent_mandate(
        principal_id=principal["id"],
        agent_id=agent["id"],
        max_per_payment_minor=100,
        max_daily_minor=100,
        currency="USD",
        allowed_rails=["internal"],
    )
    kwargs = dict(
        mandate_id=mandate["id"],
        merchant_id=merchant["id"],
        destination_account_id=merchant["settlement_account"]["id"],
        amount_minor=60,
        currency="USD",
        rail="internal",
        description="retryable",
        idempotency_key="agent-retry-1",
    )

    first = await service.create_agent_payment(**kwargs)
    retry = await service.create_agent_payment(**kwargs)
    assert retry["id"] == first["id"]

    second = await service.create_agent_payment(
        mandate_id=mandate["id"],
        merchant_id=merchant["id"],
        destination_account_id=merchant["settlement_account"]["id"],
        amount_minor=40,
        currency="USD",
        rail="internal",
        description="fills-limit",
        idempotency_key="agent-retry-2",
    )
    assert second["status"] == "pending"

    with pytest.raises(service.PaymentError, match="daily"):
        await service.create_agent_payment(
            mandate_id=mandate["id"],
            merchant_id=merchant["id"],
            destination_account_id=merchant["settlement_account"]["id"],
            amount_minor=1,
            currency="USD",
            rail="internal",
            description="over-limit",
            idempotency_key="agent-retry-3",
        )

@pytest.mark.asyncio
async def test_agent_idempotent_retry_across_utc_day_does_not_reconsume_limit(tmp_path, monkeypatch):
    service = _reload_for_db(tmp_path, monkeypatch)
    principal = service.create_identity("human", "Principal")
    agent = service.create_identity("agent", "Agent")
    merchant = service.create_merchant("Merchant", "USD")
    mandate = service.create_agent_mandate(
        principal_id=principal["id"],
        agent_id=agent["id"],
        max_per_payment_minor=100,
        max_daily_minor=100,
        currency="USD",
        allowed_rails=["internal"],
    )
    kwargs = dict(
        mandate_id=mandate["id"],
        merchant_id=merchant["id"],
        destination_account_id=merchant["settlement_account"]["id"],
        amount_minor=100,
        currency="USD",
        rail="internal",
        description="midnight-retry",
        idempotency_key="agent-midnight-1",
    )

    monkeypatch.setattr(service, "now_iso", lambda: "2026-09-07T23:59:59+00:00")
    first = await service.create_agent_payment(**kwargs)

    monkeypatch.setattr(service, "now_iso", lambda: "2026-09-08T00:00:01+00:00")
    retry = await service.create_agent_payment(**kwargs)
    assert retry["id"] == first["id"]

    fresh = await service.create_agent_payment(
        mandate_id=mandate["id"],
        merchant_id=merchant["id"],
        destination_account_id=merchant["settlement_account"]["id"],
        amount_minor=100,
        currency="USD",
        rail="internal",
        description="new-day-capacity",
        idempotency_key="agent-midnight-2",
    )
    assert fresh["status"] == "pending"
