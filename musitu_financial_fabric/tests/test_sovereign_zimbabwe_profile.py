from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest


def setup_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "zw-profile.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as db
    import app.audit as audit
    import app.sovereign as sovereign
    for mod in (config, db, audit, sovereign):
        importlib.reload(mod)
    db.init_db()
    return db, audit, sovereign


def test_zimbabwe_scheme_profile_requires_two_digit_mai_and_prevents_duplicates(tmp_path, monkeypatch):
    db, audit, sovereign = setup_modules(tmp_path, monkeypatch)
    operator = sovereign.create_scheme_participant("Reference Switch", "switch", "REFSW")

    with pytest.raises(sovereign.SovereignError, match="two-digit"):
        sovereign.register_qr_scheme_profile(
            operator["id"], "zimbabwe-2026", "9", "NS-REF-INVALID"
        )
    with pytest.raises(sovereign.SovereignError, match="two-digit"):
        sovereign.register_qr_scheme_profile(
            operator["id"], "zimbabwe-2026", "AA", "NS-REF-INVALID"
        )

    profile = sovereign.register_qr_scheme_profile(
        operator["id"], "zimbabwe-2026", "90", "NS-ALLOCATION-REFERENCE-1"
    )
    assert profile["profile_key"] == "zimbabwe-2026"
    assert profile["mai_id"] == "90"
    assert profile["allocation_ref"] == "NS-ALLOCATION-REFERENCE-1"
    assert profile["external_verification"] is False

    second = sovereign.create_scheme_participant("Second Switch", "switch", "REFSW2")
    with pytest.raises(sovereign.SovereignError, match="MAI"):
        sovereign.register_qr_scheme_profile(
            second["id"], "zimbabwe-2026", "90", "NS-ALLOCATION-REFERENCE-2"
        )
    with pytest.raises(sovereign.SovereignError, match="profile"):
        sovereign.register_qr_scheme_profile(
            operator["id"], "zimbabwe-2026", "91", "NS-ALLOCATION-REFERENCE-3"
        )

    assert audit.verify_audit_chain()[0] is True


def test_zimbabwe_dynamic_qr_requires_registered_profile_amount_and_future_expiry(tmp_path, monkeypatch):
    _, _, sovereign = setup_modules(tmp_path, monkeypatch)

    operator = sovereign.create_scheme_participant("Reference Switch", "switch", "ZWITCH")
    profile = sovereign.register_qr_scheme_profile(
        operator["id"], "zimbabwe-2026", "91", "NS-ALLOCATION-REFERENCE-ZW"
    )
    acquirer = sovereign.create_scheme_participant("Reference Acquirer", "psp", "ZWACQ")
    alias = sovereign.register_payment_alias(
        acquirer["id"], "merchant@zwacq", "tokenized-merchant-ref", "merchant"
    )
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    with pytest.raises(sovereign.SovereignError, match="dynamic"):
        sovereign.create_qr_record(
            acquirer["id"],
            "merchant-zw-1",
            alias["alias"],
            "USD",
            profile_key="zimbabwe-2026",
            scheme_profile_id=profile["id"],
            expires_at=future,
        )

    with pytest.raises(sovereign.SovereignError, match="expiry"):
        sovereign.create_qr_record(
            acquirer["id"],
            "merchant-zw-1",
            alias["alias"],
            "USD",
            amount_minor=2500,
            profile_key="zimbabwe-2026",
            scheme_profile_id=profile["id"],
        )

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with pytest.raises(sovereign.SovereignError, match="future"):
        sovereign.create_qr_record(
            acquirer["id"],
            "merchant-zw-1",
            alias["alias"],
            "USD",
            amount_minor=2500,
            expires_at=past,
            profile_key="zimbabwe-2026",
            scheme_profile_id=profile["id"],
        )

    with pytest.raises(sovereign.SovereignError, match="scheme profile"):
        sovereign.create_qr_record(
            acquirer["id"],
            "merchant-zw-1",
            alias["alias"],
            "USD",
            amount_minor=2500,
            expires_at=future,
            profile_key="zimbabwe-2026",
        )


def test_zimbabwe_dynamic_qr_emits_normalized_profile_metadata_only(tmp_path, monkeypatch):
    db, audit, sovereign = setup_modules(tmp_path, monkeypatch)
    operator = sovereign.create_scheme_participant("Reference Switch", "switch", "ZWNET")
    profile = sovereign.register_qr_scheme_profile(
        operator["id"], "zimbabwe-2026", "92", "NS-ALLOCATION-REFERENCE-92"
    )
    acquirer = sovereign.create_scheme_participant("Reference PSP", "psp", "ZWPSP")
    alias = sovereign.register_payment_alias(
        acquirer["id"], "merchant@zwpsp", "tokenized-ref", "merchant"
    )
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    qr = sovereign.create_qr_record(
        acquirer["id"],
        "merchant-zw-2",
        alias["alias"],
        "USD",
        amount_minor=9900,
        expires_at=expiry,
        profile_key="zimbabwe-2026",
        scheme_profile_id=profile["id"],
        channel="ecommerce",
    )

    assert qr["profile_key"] == "zimbabwe-2026"
    assert qr["scheme_profile_id"] == profile["id"]
    assert qr["point_of_initiation_method"] == "12"
    assert qr["reference_tag_62_05"] == qr["nonce"]
    assert qr["serialization_status"] == "normalized_not_emvco_certified"
    assert qr["channel"] == "ecommerce"

    resolved = sovereign.resolve_qr_record(qr["id"], qr["nonce"])
    assert resolved["reference_tag_62_05"] == qr["nonce"]
    assert resolved["serialization_status"] == "normalized_not_emvco_certified"

    with db.connect() as conn:
        payments = conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"]
    assert int(payments) == 0
    assert audit.verify_audit_chain()[0] is True


def test_generic_qr_remains_backward_compatible(tmp_path, monkeypatch):
    _, _, sovereign = setup_modules(tmp_path, monkeypatch)
    participant = sovereign.create_scheme_participant("Global PSP", "psp", "GLOBAL")
    alias = sovereign.register_payment_alias(
        participant["id"], "merchant@global", "global-token", "merchant"
    )

    static = sovereign.create_qr_record(
        participant["id"], "global-merchant", alias["alias"], "USD"
    )
    assert static["profile_key"] == "generic"
    assert static["point_of_initiation_method"] == "11"
    assert static["serialization_status"] == "internal_reference"

    dynamic = sovereign.create_qr_record(
        participant["id"], "global-merchant", alias["alias"], "USD", amount_minor=100
    )
    assert dynamic["profile_key"] == "generic"
    assert dynamic["point_of_initiation_method"] == "12"
    assert dynamic["reference_tag_62_05"] == dynamic["nonce"]
