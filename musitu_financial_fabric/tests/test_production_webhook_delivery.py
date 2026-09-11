from __future__ import annotations

import hashlib
import importlib
import json

import pytest


def _reload_stack(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "fabric.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as db
    import app.audit as audit
    import app.webhook as webhook
    import app.service as service
    for mod in (config, db, audit, webhook, service):
        importlib.reload(mod)
    db.init_db()
    return db, webhook, service


def _seed_payment(db, *, payment_id: str = "pay_retry", status: str = "pending"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
            ("mrc_retry", "Retry Merchant", "sandbox", "2026-09-11T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,?,?)",
            ("acct_retry", "merchant", "mrc_retry", "USD", "settlement", "active", "2026-09-11T00:00:00+00:00"),
        )
        conn.execute(
            """INSERT INTO payment_intents
               (id,merchant_id,destination_account_id,amount_minor,currency,rail,payer_ref,description,status,external_reference,idempotency_key,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payment_id,
                "mrc_retry",
                "acct_retry",
                100,
                "USD",
                "ecocash",
                "payer",
                None,
                status,
                "eco_retry",
                "idem_retry",
                "2026-09-11T00:00:00+00:00",
                "2026-09-11T00:00:00+00:00",
            ),
        )


def _body(*, event_id: str = "evt_retry", payment_id: str = "pay_retry", status: str = "succeeded") -> bytes:
    return json.dumps(
        {"event_id": event_id, "payment_id": payment_id, "status": status},
        separators=(",", ":"),
    ).encode()


def test_failed_delivery_reopens_old_receipt_for_retry(tmp_path, monkeypatch):
    db, webhook, service = _reload_stack(tmp_path, monkeypatch)
    _seed_payment(db)
    body = _body()

    assert webhook.begin_webhook_delivery("ecocash", body) == "process"
    assert service.register_webhook_event("ecocash", "evt_retry", body) is True
    webhook.finish_webhook_delivery("ecocash", body, 503)

    assert webhook.begin_webhook_delivery("ecocash", body) == "process"
    assert service.register_webhook_event("ecocash", "evt_retry", body) is True


def test_concurrent_duplicate_is_held_until_first_attempt_finishes(tmp_path, monkeypatch):
    db, webhook, service = _reload_stack(tmp_path, monkeypatch)
    _seed_payment(db)
    body = _body()

    assert webhook.begin_webhook_delivery("ecocash", body) == "process"
    assert service.register_webhook_event("ecocash", "evt_retry", body) is True
    assert webhook.begin_webhook_delivery("ecocash", body) == "inflight"


def test_crash_after_settlement_reconciles_to_processed(tmp_path, monkeypatch):
    db, webhook, service = _reload_stack(tmp_path, monkeypatch)
    _seed_payment(db)
    body = _body()

    assert webhook.begin_webhook_delivery("ecocash", body) == "process"
    assert service.register_webhook_event("ecocash", "evt_retry", body) is True
    with db.connect() as conn:
        conn.execute("UPDATE payment_intents SET status='succeeded' WHERE id=?", ("pay_retry",))

    assert webhook.begin_webhook_delivery("ecocash", body) == "processed"


def test_same_event_id_with_different_payload_fails_closed(tmp_path, monkeypatch):
    db, webhook, _ = _reload_stack(tmp_path, monkeypatch)
    _seed_payment(db)
    first = _body(status="succeeded")
    conflicting = _body(status="failed")

    assert webhook.begin_webhook_delivery("ecocash", first) == "process"
    with pytest.raises(webhook.WebhookReplayConflict):
        webhook.begin_webhook_delivery("ecocash", conflicting)


def test_delivery_state_records_payload_hash(tmp_path, monkeypatch):
    db, webhook, _ = _reload_stack(tmp_path, monkeypatch)
    _seed_payment(db)
    body = _body()
    digest = hashlib.sha256(body).hexdigest()

    assert webhook.begin_webhook_delivery("ecocash", body) == "process"
    with db.connect() as conn:
        row = conn.execute("SELECT payload_hash,state,attempts FROM webhook_delivery_state WHERE event_id=?", ("evt_retry",)).fetchone()
    assert row["payload_hash"] == digest
    assert row["state"] == "processing"
    assert int(row["attempts"]) == 1
