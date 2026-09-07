import hashlib
import hmac
import importlib
import json

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "fabric.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    monkeypatch.setenv("MUSITU_ECOCASH_WEBHOOK_SECRET", "test-secret")
    import app.config as config
    import app.db as db
    import app.audit as audit
    import app.ledger as ledger
    import app.service as service
    import app.main as main
    for mod in (config, db, audit, ledger, service, main):
        importlib.reload(mod)
    return TestClient(main.app)


def test_ecocash_webhook_cannot_mutate_non_ecocash_payment(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        merchant = client.post("/v1/merchants", json={"name": "Merchant", "currency": "USD"}).json()
        payment = client.post(
            "/v1/payments/intents",
            headers={"Idempotency-Key": "internal-webhook-1"},
            json={
                "merchant_id": merchant["id"],
                "destination_account_id": merchant["settlement_account"]["id"],
                "amount_minor": 100,
                "currency": "USD",
                "rail": "internal",
                "payer_ref": "payer",
            },
        ).json()
        assert payment["rail"] == "internal"
        assert payment["status"] == "pending"

        payload = {
            "event_id": "ecocash-event-1",
            "payment_id": payment["id"],
            "status": "succeeded",
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        response = client.post(
            "/v1/webhooks/ecocash",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-EcoCash-Signature": signature,
            },
        )

        assert response.status_code == 400
        assert "rail" in response.json()["detail"].lower()
        current = client.get(f"/v1/payments/{payment['id']}").json()
        assert current["status"] == "pending"
