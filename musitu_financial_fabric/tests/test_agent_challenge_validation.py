from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch) -> TestClient:
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


def test_agent_challenges_reject_nonpositive_amounts(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        for path in ("/mpp/challenge", "/x402/challenge"):
            for amount in (0, -1):
                response = client.get(path, params={"amount_minor": amount, "currency": "USD", "resource": "test"})
                assert response.status_code == 422


def test_agent_challenges_reject_non_ascii_currency(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        for path in ("/mpp/challenge", "/x402/challenge"):
            response = client.get(path, params={"amount_minor": 1, "currency": "ΑΒΓ", "resource": "test"})
            assert response.status_code == 422


def test_agent_challenges_reject_blank_resource(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        for path in ("/mpp/challenge", "/x402/challenge"):
            response = client.get(path, params={"amount_minor": 1, "currency": "USD", "resource": "   "})
            assert response.status_code == 422


def test_agent_challenges_normalize_valid_currency_and_resource(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        mpp = client.get("/mpp/challenge", params={"amount_minor": 1, "currency": "usd", "resource": "  test  "})
        x402 = client.get("/x402/challenge", params={"amount_minor": 1, "currency": "usd", "resource": "  test  "})
        assert mpp.status_code == 402
        assert x402.status_code == 402
        assert mpp.json()["payment"]["currency"] == "USD"
        assert mpp.json()["payment"]["resource"] == "test"
        assert x402.json()["requirements"]["currency"] == "USD"
        assert x402.json()["requirements"]["resource"] == "test"
