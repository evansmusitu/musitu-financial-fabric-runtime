from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "sovereign-qr.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as dbmod
    import app.audit as audit
    import app.sovereign as sovereign
    import app.main as main
    for mod in (config, dbmod, audit, sovereign, main):
        importlib.reload(mod)
    return TestClient(main.app)


def _participant_and_alias(client):
    participant = client.post(
        "/v1/sovereign/participants",
        json={"name": "QR Bank", "participant_type": "bank", "scheme_code": "QRBANK"},
    ).json()
    alias = client.post(
        "/v1/sovereign/aliases",
        json={"participant_id": participant["id"], "alias": "merchant@qrbank", "account_ref": "merchant-account", "alias_type": "merchant"},
    ).json()
    return participant, alias


def test_static_qr_repository_roundtrip(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        participant, alias = _participant_and_alias(client)
        created = client.post(
            "/v1/sovereign/qr",
            json={
                "participant_id": participant["id"],
                "merchant_ref": "merchant-001",
                "alias": alias["alias"],
                "currency": "USD",
            },
        )
        assert created.status_code == 200
        body = created.json()
        assert body["amount_minor"] is None
        assert body["currency"] == "USD"
        assert body["nonce"]

        resolved = client.get(f"/v1/sovereign/qr/{body['id']}", params={"nonce": body["nonce"]})
        assert resolved.status_code == 200
        assert resolved.json()["alias"] == "merchant@qrbank"
        assert resolved.json()["merchant_ref"] == "merchant-001"


def test_dynamic_qr_requires_positive_amount_and_correct_nonce(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        participant, alias = _participant_and_alias(client)
        invalid = client.post(
            "/v1/sovereign/qr",
            json={
                "participant_id": participant["id"],
                "merchant_ref": "merchant-002",
                "alias": alias["alias"],
                "currency": "USD",
                "amount_minor": 0,
            },
        )
        assert invalid.status_code == 400

        created = client.post(
            "/v1/sovereign/qr",
            json={
                "participant_id": participant["id"],
                "merchant_ref": "merchant-002",
                "alias": alias["alias"],
                "currency": "USD",
                "amount_minor": 1250,
            },
        ).json()

        wrong_nonce = client.get(f"/v1/sovereign/qr/{created['id']}", params={"nonce": "wrong"})
        assert wrong_nonce.status_code == 404


def test_qr_alias_must_belong_to_participant(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        first, alias = _participant_and_alias(client)
        second = client.post(
            "/v1/sovereign/participants",
            json={"name": "Other PSP", "participant_type": "psp", "scheme_code": "OTHERQR"},
        ).json()
        response = client.post(
            "/v1/sovereign/qr",
            json={
                "participant_id": second["id"],
                "merchant_ref": "merchant-003",
                "alias": alias["alias"],
                "currency": "USD",
            },
        )
        assert response.status_code == 400


def test_expired_dynamic_qr_fails_resolution(tmp_path, monkeypatch):
    from app import audit, db, sovereign
    from app.config import Settings

    cfg = Settings(db_path=str(tmp_path / "expired.db"), environment="sandbox")
    monkeypatch.setattr(db, "settings", cfg)
    monkeypatch.setattr(audit, "settings", cfg)
    monkeypatch.setattr(sovereign, "settings", cfg)
    db.init_db()

    participant = sovereign.create_scheme_participant("Expiry Bank", "bank", "EXPQR")
    alias = sovereign.register_payment_alias(participant["id"], "expired@bank", "acct-expired", "merchant")
    qr = sovereign.create_qr_record(
        participant["id"],
        "merchant-expired",
        alias["alias"],
        "USD",
        amount_minor=100,
        expires_at="2000-01-01T00:00:00+00:00",
    )
    assert sovereign.resolve_qr_record(qr["id"], qr["nonce"]) is None


def test_qr_creation_is_audited_but_does_not_create_payment(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        participant, alias = _participant_and_alias(client)
        created = client.post(
            "/v1/sovereign/qr",
            json={
                "participant_id": participant["id"],
                "merchant_ref": "merchant-004",
                "alias": alias["alias"],
                "currency": "USD",
                "amount_minor": 500,
            },
        )
        assert created.status_code == 200

    from app import audit, db
    valid, count, broken_at = audit.verify_audit_chain()
    assert valid is True
    assert count >= 3
    assert broken_at is None
    with db.connect() as conn:
        payment_count = conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"]
    assert int(payment_count) == 0
