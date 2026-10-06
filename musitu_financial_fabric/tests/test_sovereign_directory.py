from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as dbmod
    import app.audit as audit
    import app.main as main
    for mod in (config, dbmod, audit, main):
        importlib.reload(mod)
    return TestClient(main.app)


def test_participant_can_be_created_and_alias_resolved(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        participant_response = client.post(
            "/v1/sovereign/participants",
            json={"name": "Example Bank", "participant_type": "bank", "scheme_code": "EXBANK"},
        )
        assert participant_response.status_code == 200
        participant = participant_response.json()
        assert participant["status"] == "sandbox"
        assert participant["scheme_code"] == "EXBANK"

        alias_response = client.post(
            "/v1/sovereign/aliases",
            json={
                "participant_id": participant["id"],
                "alias": "Customer.One@Example",
                "account_ref": "acct-001",
                "alias_type": "vpa",
            },
        )
        assert alias_response.status_code == 200
        alias = alias_response.json()
        assert alias["alias"] == "customer.one@example"

        resolved = client.get("/v1/sovereign/aliases/customer.one@example")
        assert resolved.status_code == 200
        assert resolved.json()["participant_id"] == participant["id"]
        assert resolved.json()["account_ref"] == "acct-001"
