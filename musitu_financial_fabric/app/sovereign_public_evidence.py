from __future__ import annotations

from .sovereign import set_country_profile_dependency


ZIMBABWE_PUBLIC_EVIDENCE = {
    "national_switch_message_interface": {
        "status": "reference",
        "source_url": "https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf",
        "source_sections": "7.2-7.3; 17; 21.6",
        "evidence_ref": "public:rbz-qr-2026:7.2-7.3,17,21.6",
        "summary": (
            "RBZ requires default inter-provider routing and clearing through the National Switch, "
            "which also hosts the National QR Repository, and requires offline functionality to "
            "conform to National Switch technical standards."
        ),
        "limitation": (
            "The public guideline does not publish the National Switch wire protocol, endpoint "
            "contract, authentication profile, message schema, or certification fixtures."
        ),
    },
    "authoritative_mai_allocation": {
        "status": "reference",
        "source_url": "https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf",
        "source_sections": "9.1(a), 9.1(c), 9.1(e)",
        "evidence_ref": "public:rbz-qr-2026:9.1a,9.1c,9.1e",
        "summary": (
            "RBZ states that schemes/PSPs must contact the National Switch to avoid MAI ID "
            "duplication and proceed after the MAI identifier has been issued."
        ),
        "limitation": (
            "No actual MAI identifier has been issued to MUSITU and no authoritative allocation "
            "record for MUSITU is publicly available."
        ),
    },
    "emvco_conformance": {
        "status": "reference",
        "source_url": "https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf",
        "source_sections": "20.1-20.6; 21.7-21.8; Annexure 1",
        "evidence_ref": "public:rbz-qr-2026:20.1-20.6,21.7-21.8,annex1",
        "summary": (
            "RBZ adopts the EMVCo QR Code standard, prefers dynamic QR, requires amount, nonce "
            "and expiry, and identifies Point-of-Initiation Method values 11/12 plus Tag 62-05."
        ),
        "limitation": (
            "Regulatory adoption of EMVCo requirements is not evidence that MUSITU has passed "
            "EMVCo or Zimbabwe scheme conformance/certification."
        ),
    },
    "participant_certification_pack": {
        "status": "reference",
        "source_url": "https://www.rbz.co.zw/documents/Regulations_Acts/2026/QR_Code_Guideline_March_2026_signed.pdf",
        "source_sections": "6.2; 8.1; 9.1(b)-9.1(f); 18",
        "evidence_ref": "public:rbz-qr-2026:6.2,8.1,9.1b-9.1f,18",
        "summary": (
            "RBZ publishes approval, participant responsibility, scheme-rule, reporting and "
            "oversight requirements for QR payment participants."
        ),
        "limitation": (
            "The public material is not the National Switch participant certification/UAT pack "
            "and does not provide MUSITU certification status."
        ),
    },
    "settlement_finality_rules": {
        "status": "reference",
        "source_url": "https://zimswitch.co.zw/clearing-and-settlement-services/",
        "source_sections": "Clearing and Settlement Services; RBZ QR Guideline 7.3(a), 9.6",
        "evidence_ref": "public:zimswitch-clearing-settlement;rbz-qr-2026:7.3a,9.6",
        "summary": (
            "Zimswitch publicly states that it is Zimbabwe's sole National Electronic Funds "
            "Switch and clearing house and provides real-time clearing and settlement; RBZ "
            "requires scheme operating rules to cover settlement arrangements and finality."
        ),
        "limitation": (
            "The public pages do not disclose the operative settlement-finality rulebook, "
            "settlement windows, account model, liquidity rules, exception handling, or evidence "
            "needed to assert finality for a MUSITU integration."
        ),
    },
}


def apply_zimbabwe_public_reference_evidence(
    *,
    actor: str,
    authorization_decision_id: str,
) -> list[dict]:
    actor = str(actor or "").strip()
    authorization_decision_id = str(authorization_decision_id or "").strip()
    if not actor:
        raise ValueError("public evidence actor is required")
    if not authorization_decision_id:
        raise ValueError("public evidence authorization decision is required")

    applied: list[dict] = []
    for dependency_key, evidence in ZIMBABWE_PUBLIC_EVIDENCE.items():
        applied.append(
            set_country_profile_dependency(
                "zimbabwe-2026",
                dependency_key,
                "reference",
                evidence_ref=evidence["evidence_ref"],
                actor=actor,
                authorization_decision_id=authorization_decision_id,
            )
        )
    return applied
