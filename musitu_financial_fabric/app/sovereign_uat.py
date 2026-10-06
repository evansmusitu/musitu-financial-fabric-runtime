from __future__ import annotations

import asyncio
import uuid

from .audit import verify_audit_chain
from .db import connect
from .sovereign import (
    calculate_net_positions,
    close_settlement_cycle,
    country_profile_gate,
    create_certification_case,
    create_request_to_pay,
    create_scheme_exception,
    create_scheme_participant,
    decide_certification,
    decide_scheme_exception,
    open_settlement_cycle,
    record_certification_check,
    record_clearing_obligation,
    record_exception_evidence,
    register_payment_alias,
    respond_request_to_pay,
)
from .switch_contracts import (
    SwitchContractError,
    UnconfiguredSovereignSwitchAdapter,
    instruction_from_accepted_request,
)


def _certify(participant_id: str, suffix: str, role: str) -> dict:
    case = create_certification_case(
        participant_id,
        "reference-uat",
        f"reference-evaluation:{suffix}:{role}",
        ["security", "interoperability"],
    )
    record_certification_check(
        case["id"], "security", "passed", f"reference-security:{suffix}:{role}", "uat-verifier"
    )
    record_certification_check(
        case["id"], "interoperability", "passed", f"reference-interop:{suffix}:{role}", "uat-verifier"
    )
    return decide_certification(
        case["id"], "approved", "uat-operator", f"reference-authz:{suffix}:{role}"
    )


def run_reference_uat(scenario: str) -> dict:
    scenario = str(scenario or "").strip()
    if not scenario:
        raise ValueError("scenario is required")

    suffix = uuid.uuid4().hex[:10]

    payer = create_scheme_participant(
        "Reference Payer Bank", "bank", f"UATP{suffix}".upper()
    )
    payee = create_scheme_participant(
        "Reference Merchant PSP", "psp", f"UATM{suffix}".upper()
    )

    payer_cert = _certify(payer["id"], suffix, "payer")
    payee_cert = _certify(payee["id"], suffix, "payee")

    payer_alias = register_payment_alias(
        payer["id"], f"payer-{suffix}@uat", f"payer-token-{suffix}", "vpa"
    )
    payee_alias = register_payment_alias(
        payee["id"], f"merchant-{suffix}@uat", f"merchant-token-{suffix}", "merchant"
    )

    request = create_request_to_pay(
        payee_alias["alias"],
        payer_alias["alias"],
        1250,
        "USD",
        f"{scenario}-invoice",
        f"uat-rtp-{suffix}",
    )
    accepted = respond_request_to_pay(request["id"], "accepted", payer_alias["alias"])

    instruction = instruction_from_accepted_request(
        accepted,
        payer_participant_id=payer["id"],
        payee_participant_id=payee["id"],
        idempotency_key=f"uat-switch-{suffix}",
    )

    submission_status = "unexpected_success"
    try:
        asyncio.run(UnconfiguredSovereignSwitchAdapter().submit_transfer(instruction))
    except SwitchContractError:
        submission_status = "blocked_unconfigured"

    cycle = open_settlement_cycle("reference-uat", f"cycle-{suffix}", "USD")
    record_clearing_obligation(
        cycle["id"], payer["id"], payee["id"], 1250, f"uat-obligation-{suffix}"
    )
    positions = calculate_net_positions(cycle["id"])
    closed = close_settlement_cycle(
        cycle["id"],
        f"reference-only-settlement-evidence:{suffix}",
        "uat-operator",
        f"uat-close-authz-{suffix}",
    )

    exception = create_scheme_exception(
        f"reference-switch-transaction-{suffix}",
        "dispute",
        payee["id"],
        "reference-uat-dispute",
        f"uat-exception-{suffix}",
    )
    record_exception_evidence(
        exception["id"], f"reference-evidence-{suffix}", "uat-claims"
    )
    decided_exception = decide_scheme_exception(
        exception["id"], "accepted", "uat-operator", f"uat-dispute-authz-{suffix}"
    )

    gate = country_profile_gate("zimbabwe-2026")
    audit_valid, audit_events, audit_broken_at = verify_audit_chain()

    with connect() as conn:
        payment_intents = int(
            conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"]
        )
        ledger_postings = int(
            conn.execute("SELECT COUNT(*) AS n FROM ledger_postings").fetchone()["n"]
        )

    return {
        "scenario": scenario,
        "payer": {
            "participant_id": payer["id"],
            "certification_status": payer_cert["status"],
            "alias": payer_alias["alias"],
        },
        "payee": {
            "participant_id": payee["id"],
            "certification_status": payee_cert["status"],
            "alias": payee_alias["alias"],
        },
        "request_to_pay": {
            "id": accepted["id"],
            "status": accepted["status"],
        },
        "switch": {
            "instruction": instruction.to_dict(),
            "submission_status": submission_status,
        },
        "clearing": {
            "cycle_id": cycle["id"],
            "balanced": positions["balanced"],
            "sum_minor": positions["sum_minor"],
            "positions_minor": positions["positions_minor"],
            "status": closed["status"],
            "external_settlement_verified": closed["external_settlement_verified"],
        },
        "exception": {
            "id": decided_exception["id"],
            "status": decided_exception["status"],
            "kind": decided_exception["kind"],
        },
        "country_gate": gate,
        "audit": {
            "valid": audit_valid,
            "events": audit_events,
            "broken_at": audit_broken_at,
        },
        "side_effects": {
            "payment_intents": payment_intents,
            "ledger_postings": ledger_postings,
        },
        "live_funds_moved": False,
        "production_authorized": False,
    }
