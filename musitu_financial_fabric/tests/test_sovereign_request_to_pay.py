from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def client_for(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "sovereign-rtp.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as dbmod
    import app.audit as audit
    import app.sovereign as sovereign
    import app.main as main
    for mod in (config, dbmod, audit, sovereign, main):
        importlib.reload(mod)
    return TestClient(main.app)


def _setup_aliases(client):
    payer_participant = client.post(
        "/v1/sovereign/participants",
        json={"name": "Payer Bank", "participant_type": "bank", "scheme_code": "PAYERBANK"},
    ).json()
    payee_participant = client.post(
        "/v1/sovereign/participants",
        json={"name": "Payee PSP", "participant_type": "psp", "scheme_code": "PAYEEPSP"},
    ).json()
    payer = client.post(
        "/v1/sovereign/aliases",
        json={"participant_id": payer_participant["id"], "alias": "payer@bank", "account_ref": "payer-account", "alias_type": "vpa"},
    ).json()
    payee = client.post(
        "/v1/sovereign/aliases",
        json={"participant_id": payee_participant["id"], "alias": "merchant@psp", "account_ref": "merchant-account", "alias_type": "merchant"},
    ).json()
    return payer, payee


def test_request_to_pay_is_idempotent_and_acceptance_produces_instruction_only(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        payer, payee = _setup_aliases(client)
        payload = {
            "payee_alias": payee["alias"],
            "payer_alias": payer["alias"],
            "amount_minor": 2500,
            "currency": "USD",
            "reference": "invoice-100",
        }
        first = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-1"},
            json=payload,
        )
        assert first.status_code == 200
        second = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-1"},
            json=payload,
        )
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]

        accepted = client.post(
            f"/v1/sovereign/requests-to-pay/{first.json()['id']}/response",
            json={"decision": "accepted", "actor_alias": payer["alias"]},
        )
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["status"] == "accepted"
        assert body["payment_instruction"]["amount_minor"] == 2500
        assert body["payment_instruction"]["payer_alias"] == "payer@bank"
        assert body["payment_instruction"]["payee_alias"] == "merchant@psp"

    from app import db
    with db.connect() as conn:
        payments = conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"]
    assert int(payments) == 0


def test_idempotency_key_conflict_fails_closed(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        payer, payee = _setup_aliases(client)
        base = {
            "payee_alias": payee["alias"],
            "payer_alias": payer["alias"],
            "amount_minor": 100,
            "currency": "USD",
            "reference": "invoice-conflict",
        }
        assert client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-conflict"},
            json=base,
        ).status_code == 200
        changed = dict(base)
        changed["amount_minor"] = 101
        conflict = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-conflict"},
            json=changed,
        )
        assert conflict.status_code == 400


def test_only_payer_can_accept_or_decline_and_payee_can_cancel(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        payer, payee = _setup_aliases(client)
        request = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-actor"},
            json={
                "payee_alias": payee["alias"],
                "payer_alias": payer["alias"],
                "amount_minor": 300,
                "currency": "USD",
                "reference": "invoice-actor",
            },
        ).json()

        wrong_actor = client.post(
            f"/v1/sovereign/requests-to-pay/{request['id']}/response",
            json={"decision": "accepted", "actor_alias": payee["alias"]},
        )
        assert wrong_actor.status_code == 400

        cancelled = client.post(
            f"/v1/sovereign/requests-to-pay/{request['id']}/response",
            json={"decision": "cancelled", "actor_alias": payee["alias"]},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        terminal_change = client.post(
            f"/v1/sovereign/requests-to-pay/{request['id']}/response",
            json={"decision": "accepted", "actor_alias": payer["alias"]},
        )
        assert terminal_change.status_code == 400


def test_request_to_pay_requires_resolvable_aliases_positive_amount_and_currency(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        payer, payee = _setup_aliases(client)
        invalid_amount = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-invalid-amount"},
            json={
                "payee_alias": payee["alias"],
                "payer_alias": payer["alias"],
                "amount_minor": 0,
                "currency": "USD",
                "reference": "bad-amount",
            },
        )
        assert invalid_amount.status_code == 400

        invalid_currency = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-invalid-currency"},
            json={
                "payee_alias": payee["alias"],
                "payer_alias": payer["alias"],
                "amount_minor": 100,
                "currency": "US1",
                "reference": "bad-currency",
            },
        )
        assert invalid_currency.status_code == 400

        missing_alias = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-missing-alias"},
            json={
                "payee_alias": "missing@payee",
                "payer_alias": payer["alias"],
                "amount_minor": 100,
                "currency": "USD",
                "reference": "bad-alias",
            },
        )
        assert missing_alias.status_code == 400


def test_suspended_actor_alias_cannot_respond_to_pending_request(tmp_path, monkeypatch):
    with client_for(tmp_path, monkeypatch) as client:
        payer, payee = _setup_aliases(client)
        request = client.post(
            "/v1/sovereign/requests-to-pay",
            headers={"Idempotency-Key": "rtp-suspended-actor"},
            json={
                "payee_alias": payee["alias"],
                "payer_alias": payer["alias"],
                "amount_minor": 450,
                "currency": "USD",
                "reference": "invoice-suspended",
            },
        ).json()

        activated = client.post(
            f"/v1/sovereign/participants/{payer['participant_id']}/status",
            json={"status": "active", "evidence_ref": "sandbox-activate"},
        )
        assert activated.status_code == 200
        suspended = client.post(
            f"/v1/sovereign/participants/{payer['participant_id']}/status",
            json={"status": "suspended", "evidence_ref": "sandbox-suspend"},
        )
        assert suspended.status_code == 200

        response = client.post(
            f"/v1/sovereign/requests-to-pay/{request['id']}/response",
            json={"decision": "accepted", "actor_alias": payer["alias"]},
        )
        assert response.status_code == 400
