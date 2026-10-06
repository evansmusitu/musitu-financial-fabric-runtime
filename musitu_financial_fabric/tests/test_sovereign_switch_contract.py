from __future__ import annotations

import asyncio

import pytest

from app import audit, db, sovereign
from app.config import Settings
from app.switch_contracts import (
    SwitchContractError,
    SwitchTransferInstruction,
    UnconfiguredSovereignSwitchAdapter,
    instruction_from_accepted_request,
)


def setup_env(tmp_path):
    cfg = Settings(db_path=str(tmp_path / "switch.db"), environment="sandbox")
    db.settings = cfg
    audit.settings = cfg
    sovereign.settings = cfg
    db.init_db()


def test_instruction_validation_and_unconfigured_adapter_fail_closed():
    with pytest.raises(SwitchContractError, match="positive"):
        SwitchTransferInstruction("idem","p1","p2","a@x","b@y",0,"USD","ref")
    with pytest.raises(SwitchContractError, match="currency"):
        SwitchTransferInstruction("idem","p1","p2","a@x","b@y",1,"US1","ref")
    instruction = SwitchTransferInstruction("idem","p1","p2"," A@X "," B@Y ",1,"usd","ref")
    assert instruction.currency == "USD"
    assert instruction.payer_alias == "a@x"
    adapter = UnconfiguredSovereignSwitchAdapter()
    with pytest.raises(SwitchContractError, match="not configured"):
        asyncio.run(adapter.submit_transfer(instruction))


def test_accepted_request_transforms_without_payment_side_effect(tmp_path):
    setup_env(tmp_path)
    payerp = sovereign.create_scheme_participant("Payer Bank","bank","SWPAY")
    payeep = sovereign.create_scheme_participant("Payee PSP","psp","SWREC")
    payer = sovereign.register_payment_alias(payerp["id"],"payer@bank","payer-token","vpa")
    payee = sovereign.register_payment_alias(payeep["id"],"merchant@psp","payee-token","merchant")
    req = sovereign.create_request_to_pay(payee["alias"],payer["alias"],777,"USD","invoice-switch","rtp-switch")
    accepted = sovereign.respond_request_to_pay(req["id"],"accepted",payer["alias"])
    instruction = instruction_from_accepted_request(
        accepted,
        payer_participant_id=payerp["id"],
        payee_participant_id=payeep["id"],
        idempotency_key="switch-submit-1",
    )
    assert instruction.request_to_pay_id == req["id"]
    assert instruction.amount_minor == 777
    assert instruction.reference == "invoice-switch"
    assert instruction.payer_alias == payer["alias"]
    assert instruction.payee_alias == payee["alias"]
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"] == 0


def test_nonaccepted_request_cannot_be_transformed():
    with pytest.raises(SwitchContractError, match="accepted"):
        instruction_from_accepted_request(
            {"id":"rtp-x","status":"pending","payer_alias":"a@x","payee_alias":"b@y","amount_minor":1,"currency":"USD","reference":"x"},
            payer_participant_id="p1",payee_participant_id="p2",idempotency_key="idem-x"
        )
