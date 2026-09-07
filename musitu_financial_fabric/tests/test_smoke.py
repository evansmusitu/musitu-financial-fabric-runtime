import importlib

from fastapi.testclient import TestClient


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "fabric.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    monkeypatch.setenv("MUSITU_ECOCASH_WEBHOOK_SECRET", "test-secret")
    import app.config as config
    import app.db as dbmod
    import app.audit as audit
    import app.ledger as ledger
    import app.service as service
    import app.main as main
    for mod in (config, dbmod, audit, ledger, service, main):
        importlib.reload(mod)
    return TestClient(main.app)


def test_mandatory_component_surface(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        payload = client.get("/v1/fabric/components").json()
        assert payload["required"] is True
        assert len(payload["components"]) == 39
        assert all(item["required"] is True for item in payload["components"])


def test_payment_intent_routes_to_internal_sandbox(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        merchant = client.post("/v1/merchants", json={"name":"Sandbox Merchant","currency":"USD"}).json()
        account = merchant["settlement_account"]["id"]
        result = client.post(
            "/v1/payments/intents",
            headers={"Idempotency-Key":"smoke-1"},
            json={
                "merchant_id":merchant["id"],
                "destination_account_id":account,
                "amount_minor":100,
                "currency":"USD",
                "rail":"auto",
                "payer_ref":"sandbox-payer"
            },
        )
        assert result.status_code == 200
        body = result.json()
        assert body["rail"] == "internal"
        assert body["status"] == "pending"


def test_agent_protocol_challenges(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        mpp = client.get("/mpp/challenge", params={"amount_minor":1,"currency":"USD","resource":"test"})
        x402 = client.get("/x402/challenge", params={"amount_minor":1,"currency":"USD","resource":"test"})
        assert mpp.status_code == 402
        assert x402.status_code == 402
        assert mpp.json()["payment"]["method"] == "musitu"
        assert x402.json()["requirements"]["scheme"] == "musitu"


def test_readiness_fails_closed_without_external_runtime(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        body = client.get("/v1/fabric/readiness").json()
        assert body["sandbox_api_operational"] is True
        assert body["all_required_runtime_healthy"] is False
        assert body["production_funds_gate"] is False
