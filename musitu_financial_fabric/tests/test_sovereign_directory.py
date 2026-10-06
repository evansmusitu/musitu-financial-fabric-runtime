from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "sovereign.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as dbmod
    import app.audit as audit
    import app.sovereign as sovereign
    import app.main as main
    for mod in (config, dbmod, audit, sovereign, main):
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


def test_duplicate_scheme_code_and_normalized_alias_fail(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        first = client.post(
            "/v1/sovereign/participants",
            json={"name": "Bank One", "participant_type": "bank", "scheme_code": "BANK1"},
        )
        assert first.status_code == 200
        duplicate_participant = client.post(
            "/v1/sovereign/participants",
            json={"name": "Bank Duplicate", "participant_type": "bank", "scheme_code": "BANK1"},
        )
        assert duplicate_participant.status_code == 400

        participant_id = first.json()["id"]
        first_alias = client.post(
            "/v1/sovereign/aliases",
            json={"participant_id": participant_id, "alias": "User@Bank", "account_ref": "a1", "alias_type": "vpa"},
        )
        assert first_alias.status_code == 200
        duplicate_alias = client.post(
            "/v1/sovereign/aliases",
            json={"participant_id": participant_id, "alias": " user@bank ", "account_ref": "a2", "alias_type": "vpa"},
        )
        assert duplicate_alias.status_code == 400


def test_production_activation_requires_evidence_actor_and_authorization(tmp_path, monkeypatch):
    from app import audit, db, sovereign
    from app.config import Settings

    cfg = Settings(db_path=str(tmp_path / "production-directory.db"), environment="production")
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(audit, "settings", cfg)
    monkeypatch.setattr(sovereign, "settings", cfg)
    db.init_db()

    participant = sovereign.create_scheme_participant("Production Bank", "bank", "PRODBANK")
    assert participant["status"] == "pending_review"

    with pytest.raises(sovereign.SovereignError, match="evidence"):
        sovereign.set_participant_status(
            participant["id"], "active", evidence_ref="", actor="operator-1", authorization_decision_id="authz-1"
        )
    with pytest.raises(sovereign.SovereignError, match="actor"):
        sovereign.set_participant_status(
            participant["id"], "active", evidence_ref="RBZ-APPROVAL-1", actor="", authorization_decision_id="authz-1"
        )
    with pytest.raises(sovereign.SovereignError, match="authorization"):
        sovereign.set_participant_status(
            participant["id"], "active", evidence_ref="RBZ-APPROVAL-1", actor="operator-1", authorization_decision_id=""
        )

    activated = sovereign.set_participant_status(
        participant["id"],
        "active",
        evidence_ref="RBZ-APPROVAL-1",
        actor="operator-1",
        authorization_decision_id="authz-1",
    )
    assert activated["status"] == "active"


def test_suspended_participant_alias_fails_closed_and_reactivation_restores_resolution(tmp_path, monkeypatch):
    from app import audit, db, sovereign
    from app.config import Settings

    cfg = Settings(db_path=str(tmp_path / "suspension.db"), environment="sandbox")
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(audit, "settings", cfg)
    monkeypatch.setattr(sovereign, "settings", cfg)
    db.init_db()

    participant = sovereign.create_scheme_participant("Sandbox PSP", "psp", "PSP1")
    alias = sovereign.register_payment_alias(participant["id"], "payer@psp", "acct-payer", "vpa")
    assert sovereign.resolve_payment_alias(alias["alias"]) is not None

    activated = sovereign.set_participant_status(
        participant["id"], "active", evidence_ref="sandbox-activation", actor="sandbox", authorization_decision_id="sandbox"
    )
    assert activated["status"] == "active"

    suspended = sovereign.set_participant_status(
        participant["id"], "suspended", evidence_ref="sandbox-risk-hold", actor="sandbox", authorization_decision_id="sandbox"
    )
    assert suspended["status"] == "suspended"
    assert sovereign.resolve_payment_alias(alias["alias"]) is None

    active = sovereign.set_participant_status(
        participant["id"], "active", evidence_ref="sandbox-risk-clear", actor="sandbox", authorization_decision_id="sandbox"
    )
    assert active["status"] == "active"
    assert sovereign.resolve_payment_alias(alias["alias"])["account_ref"] == "acct-payer"


def test_directory_mutations_preserve_audit_chain(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        participant = client.post(
            "/v1/sovereign/participants",
            json={"name": "Audit Bank", "participant_type": "bank", "scheme_code": "AUDIT1"},
        ).json()
        client.post(
            "/v1/sovereign/aliases",
            json={"participant_id": participant["id"], "alias": "audit@bank", "account_ref": "audit-account", "alias_type": "vpa"},
        )

    from app import audit
    valid, count, broken_at = audit.verify_audit_chain()
    assert valid is True
    assert count >= 2
    assert broken_at is None
