from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .audit import append_audit, now_iso
from .config import settings
from .db import connect


class SovereignError(RuntimeError):
    pass


PARTICIPANT_TYPES = {"bank", "mobile_money", "fintech", "government", "switch", "psp"}
ALIAS_TYPES = {"phone", "email", "vpa", "merchant", "account"}

_SOVEREIGN_CAPABILITIES = (
    {
        "key": "sovereign-directory",
        "name": "Sovereign Participant and Alias Directory",
        "phase": "reference",
        "production_enabled": False,
        "moves_funds": False,
    },
    {
        "key": "sovereign-qr",
        "name": "Sovereign QR Repository",
        "phase": "reference",
        "production_enabled": False,
        "moves_funds": False,
    },
    {
        "key": "request-to-pay",
        "name": "Sovereign Request to Pay",
        "phase": "reference",
        "production_enabled": False,
        "moves_funds": False,
    },
    {
        "key": "zimbabwe-qr-profile",
        "name": "Zimbabwe 2026 QR Reference Profile",
        "phase": "reference",
        "production_enabled": False,
        "moves_funds": False,
    },
    {
        "key": "participant-certification",
        "name": "Sovereign Participant Certification",
        "phase": "reference",
        "production_enabled": False,
        "moves_funds": False,
    },
)


def sovereign_capabilities() -> list[dict]:
    return [dict(item) for item in _SOVEREIGN_CAPABILITIES]

PARTICIPANT_TRANSITIONS = {
    "pending_review": {"active", "rejected"},
    "sandbox": {"active", "rejected"},
    "active": {"suspended"},
    "suspended": {"active", "rejected"},
}


def set_participant_status(
    participant_id: str,
    target_status: str,
    *,
    evidence_ref: str,
    actor: str,
    authorization_decision_id: str,
) -> dict:
    participant_id = str(participant_id or "").strip()
    target_status = str(target_status or "").strip().lower()
    evidence_ref = str(evidence_ref or "").strip()
    actor = str(actor or "").strip()
    authorization_decision_id = str(authorization_decision_id or "").strip()

    if target_status not in {"active", "suspended", "rejected"}:
        raise SovereignError("unsupported participant target status")
    if settings.is_production:
        if not evidence_ref:
            raise SovereignError("production participant status change requires evidence")
        if not actor:
            raise SovereignError("production participant status change requires actor")
        if not authorization_decision_id:
            raise SovereignError("production participant status change requires authorization decision")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM scheme_participants WHERE id=?",
                (participant_id,),
            ).fetchone()
            if not row:
                raise SovereignError("scheme participant not found")
            participant = dict(row)
            current = str(participant["status"])
            if current == target_status:
                conn.execute("COMMIT")
                return participant
            if target_status not in PARTICIPANT_TRANSITIONS.get(current, set()):
                raise SovereignError(f"participant transition {current}->{target_status} is not allowed")
            updated = conn.execute(
                "UPDATE scheme_participants SET status=? WHERE id=? AND status=?",
                (target_status, participant_id, current),
            )
            if updated.rowcount != 1:
                raise SovereignError("participant state changed before status commit")
            append_audit(
                "sovereign.participant_status_changed",
                participant_id,
                {
                    "previous_status": current,
                    "target_status": target_status,
                    "evidence_ref": evidence_ref,
                    "actor": actor or "sandbox",
                    "authorization_decision_id": authorization_decision_id or "sandbox",
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    with connect() as conn:
        result = conn.execute(
            "SELECT * FROM scheme_participants WHERE id=?",
            (participant_id,),
        ).fetchone()
    if not result:
        raise SovereignError("scheme participant disappeared after status change")
    return dict(result)


def create_scheme_participant(name: str, participant_type: str, scheme_code: str) -> dict:
    name = str(name or "").strip()
    participant_type = str(participant_type or "").strip().lower()
    scheme_code = str(scheme_code or "").strip()
    if not name:
        raise SovereignError("participant name is required")
    if participant_type not in PARTICIPANT_TYPES:
        raise SovereignError("unsupported participant type")
    if not scheme_code:
        raise SovereignError("scheme code is required")

    participant_id = f"spn_{uuid.uuid4().hex}"
    status = "pending_review" if settings.is_production else "sandbox"
    created_at = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT id FROM scheme_participants WHERE scheme_code=?",
                (scheme_code,),
            ).fetchone()
            if existing:
                raise SovereignError("scheme code already exists")
            conn.execute(
                """INSERT INTO scheme_participants
                   (id,name,participant_type,scheme_code,status,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (participant_id, name, participant_type, scheme_code, status, created_at),
            )
            append_audit(
                "sovereign.participant_created",
                participant_id,
                {
                    "name": name,
                    "participant_type": participant_type,
                    "scheme_code": scheme_code,
                    "status": status,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {
        "id": participant_id,
        "name": name,
        "participant_type": participant_type,
        "scheme_code": scheme_code,
        "status": status,
        "created_at": created_at,
    }


def register_payment_alias(participant_id: str, alias: str, account_ref: str, alias_type: str) -> dict:
    participant_id = str(participant_id or "").strip()
    normalized_alias = str(alias or "").strip().lower()
    account_ref = str(account_ref or "").strip()
    alias_type = str(alias_type or "").strip().lower()
    if not normalized_alias:
        raise SovereignError("payment alias is required")
    if not account_ref:
        raise SovereignError("account reference is required")
    if alias_type not in ALIAS_TYPES:
        raise SovereignError("unsupported alias type")

    alias_id = f"als_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            participant = conn.execute(
                "SELECT * FROM scheme_participants WHERE id=?",
                (participant_id,),
            ).fetchone()
            if not participant:
                raise SovereignError("scheme participant not found")
            if participant["status"] == "rejected":
                raise SovereignError("rejected participant cannot register aliases")
            existing = conn.execute(
                "SELECT id FROM payment_aliases WHERE alias=?",
                (normalized_alias,),
            ).fetchone()
            if existing:
                raise SovereignError("payment alias already exists")
            conn.execute(
                """INSERT INTO payment_aliases
                   (id,participant_id,alias,account_ref,alias_type,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (alias_id, participant_id, normalized_alias, account_ref, alias_type, created_at),
            )
            append_audit(
                "sovereign.alias_registered",
                alias_id,
                {
                    "participant_id": participant_id,
                    "alias": normalized_alias,
                    "account_ref": account_ref,
                    "alias_type": alias_type,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {
        "id": alias_id,
        "participant_id": participant_id,
        "alias": normalized_alias,
        "account_ref": account_ref,
        "alias_type": alias_type,
        "created_at": created_at,
    }


def resolve_payment_alias(alias: str) -> dict | None:
    normalized_alias = str(alias or "").strip().lower()
    if not normalized_alias:
        return None
    with connect() as conn:
        row = conn.execute(
            """SELECT a.id,a.participant_id,a.alias,a.account_ref,a.alias_type,a.created_at,
                      p.name AS participant_name,p.participant_type,p.scheme_code,p.status AS participant_status
               FROM payment_aliases a
               JOIN scheme_participants p ON p.id=a.participant_id
               WHERE a.alias=?""",
            (normalized_alias,),
        ).fetchone()
    if not row or row["participant_status"] not in {"active", "sandbox"}:
        return None
    return dict(row)


def register_qr_scheme_profile(
    participant_id: str,
    profile_key: str,
    mai_id: str,
    allocation_ref: str,
) -> dict:
    participant_id = str(participant_id or "").strip()
    profile_key = str(profile_key or "").strip().lower()
    mai_id = str(mai_id or "").strip()
    allocation_ref = str(allocation_ref or "").strip()
    if not participant_id:
        raise SovereignError("scheme participant is required")
    if not profile_key:
        raise SovereignError("QR profile key is required")
    if len(mai_id) != 2 or not mai_id.isdigit():
        raise SovereignError("MAI identifier must be a two-digit numeric value")
    if not allocation_ref:
        raise SovereignError("MAI allocation reference is required")

    profile_id = f"qsp_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            participant = conn.execute(
                "SELECT * FROM scheme_participants WHERE id=?",
                (participant_id,),
            ).fetchone()
            if not participant:
                raise SovereignError("scheme participant not found")
            if participant["status"] not in {"active", "sandbox"}:
                raise SovereignError("scheme participant is not active for QR profile registration")

            existing_mai = conn.execute(
                "SELECT id FROM qr_scheme_profiles WHERE profile_key=? AND mai_id=?",
                (profile_key, mai_id),
            ).fetchone()
            if existing_mai:
                raise SovereignError("MAI identifier is already registered for this profile")
            existing_participant = conn.execute(
                "SELECT id FROM qr_scheme_profiles WHERE profile_key=? AND participant_id=?",
                (profile_key, participant_id),
            ).fetchone()
            if existing_participant:
                raise SovereignError("participant already has a QR scheme profile")

            conn.execute(
                """INSERT INTO qr_scheme_profiles
                   (id,participant_id,profile_key,mai_id,allocation_ref,external_verification,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (profile_id, participant_id, profile_key, mai_id, allocation_ref, False, created_at),
            )
            append_audit(
                "sovereign.qr_scheme_profile_registered",
                profile_id,
                {
                    "participant_id": participant_id,
                    "profile_key": profile_key,
                    "mai_id": mai_id,
                    "allocation_ref": allocation_ref,
                    "external_verification": False,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    return {
        "id": profile_id,
        "participant_id": participant_id,
        "profile_key": profile_key,
        "mai_id": mai_id,
        "allocation_ref": allocation_ref,
        "external_verification": False,
        "created_at": created_at,
    }


def _certification_case_public(row: dict) -> dict:
    return {
        "id": row["id"],
        "participant_id": row["participant_id"],
        "scheme_profile": row["scheme_profile"],
        "evidence_ref": row["evidence_ref"],
        "required_checks": sorted(json.loads(row["required_checks_json"])),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_certification_case(
    participant_id: str,
    scheme_profile: str,
    evidence_ref: str,
    required_checks: list[str],
) -> dict:
    participant_id = str(participant_id or "").strip()
    scheme_profile = str(scheme_profile or "").strip().lower()
    evidence_ref = str(evidence_ref or "").strip()
    required = sorted({str(item or "").strip().lower() for item in required_checks if str(item or "").strip()})
    if not participant_id:
        raise SovereignError("scheme participant is required")
    if not scheme_profile:
        raise SovereignError("certification scheme profile is required")
    if not evidence_ref:
        raise SovereignError("certification evidence reference is required")
    if not required:
        raise SovereignError("at least one mandatory certification check is required")

    case_id = f"crt_{uuid.uuid4().hex}"
    ts = now_iso()
    required_json = json.dumps(required, separators=(",", ":"))
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            participant = conn.execute(
                "SELECT * FROM scheme_participants WHERE id=?",
                (participant_id,),
            ).fetchone()
            if not participant:
                raise SovereignError("scheme participant not found")
            if participant["status"] == "rejected":
                raise SovereignError("rejected participant cannot enter certification")
            conn.execute(
                """INSERT INTO scheme_certification_cases
                   (id,participant_id,scheme_profile,evidence_ref,required_checks_json,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (case_id, participant_id, scheme_profile, evidence_ref, required_json, "open", ts, ts),
            )
            append_audit(
                "sovereign.certification_case_created",
                case_id,
                {
                    "participant_id": participant_id,
                    "scheme_profile": scheme_profile,
                    "evidence_ref": evidence_ref,
                    "required_checks": required,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {
        "id": case_id,
        "participant_id": participant_id,
        "scheme_profile": scheme_profile,
        "evidence_ref": evidence_ref,
        "required_checks": required,
        "status": "open",
        "created_at": ts,
        "updated_at": ts,
    }


def record_certification_check(
    case_id: str,
    check_key: str,
    result: str,
    evidence_ref: str,
    actor: str,
) -> dict:
    case_id = str(case_id or "").strip()
    check_key = str(check_key or "").strip().lower()
    result = str(result or "").strip().lower()
    evidence_ref = str(evidence_ref or "").strip()
    actor = str(actor or "").strip()
    if result not in {"passed", "failed"}:
        raise SovereignError("certification check result must be passed or failed")
    if not check_key:
        raise SovereignError("certification check key is required")
    if not evidence_ref:
        raise SovereignError("certification check evidence is required")
    if not actor:
        raise SovereignError("certification check actor is required")
    payload = {"check_key": check_key, "result": result, "evidence_ref": evidence_ref, "actor": actor}
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            case = conn.execute("SELECT * FROM scheme_certification_cases WHERE id=?", (case_id,)).fetchone()
            if not case:
                raise SovereignError("certification case not found")
            if case["status"] != "open":
                raise SovereignError("certification case is terminal")
            required = set(json.loads(case["required_checks_json"]))
            if check_key not in required:
                raise SovereignError("certification check is not a required check")
            existing = conn.execute(
                "SELECT * FROM scheme_certification_checks WHERE case_id=? AND check_key=?",
                (case_id, check_key),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise SovereignError("conflicting certification check replay")
                conn.execute("COMMIT")
                return dict(existing)
            check_id = f"chk_{uuid.uuid4().hex}"
            created_at = now_iso()
            conn.execute(
                """INSERT INTO scheme_certification_checks
                   (id,case_id,check_key,result,evidence_ref,actor,payload_hash,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (check_id, case_id, check_key, result, evidence_ref, actor, payload_hash, created_at),
            )
            append_audit(
                "sovereign.certification_check_recorded",
                check_id,
                payload | {"case_id": case_id},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {
        "id": check_id,
        "case_id": case_id,
        "check_key": check_key,
        "result": result,
        "evidence_ref": evidence_ref,
        "actor": actor,
        "payload_hash": payload_hash,
        "created_at": created_at,
    }


def decide_certification(
    case_id: str,
    decision: str,
    actor: str,
    authorization_decision_id: str,
) -> dict:
    case_id = str(case_id or "").strip()
    decision = str(decision or "").strip().lower()
    actor = str(actor or "").strip()
    authorization_decision_id = str(authorization_decision_id or "").strip()
    if decision not in {"approved", "rejected"}:
        raise SovereignError("unsupported certification decision")
    if not actor:
        raise SovereignError("certification decision actor is required")
    if not authorization_decision_id:
        raise SovereignError("certification authorization decision is required")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            case = conn.execute("SELECT * FROM scheme_certification_cases WHERE id=?", (case_id,)).fetchone()
            if not case:
                raise SovereignError("certification case not found")
            if case["status"] != "open":
                raise SovereignError("certification case is terminal")
            if decision == "approved":
                required = set(json.loads(case["required_checks_json"]))
                checks = conn.execute(
                    "SELECT check_key,result FROM scheme_certification_checks WHERE case_id=?",
                    (case_id,),
                ).fetchall()
                passed = {row["check_key"] for row in checks if row["result"] == "passed"}
                if passed != required:
                    raise SovereignError("all mandatory certification checks must pass before approval")
            ts = now_iso()
            updated = conn.execute(
                "UPDATE scheme_certification_cases SET status=?,updated_at=? WHERE id=? AND status='open'",
                (decision, ts, case_id),
            )
            if updated.rowcount != 1:
                raise SovereignError("certification case changed before decision commit")
            append_audit(
                "sovereign.certification_decided",
                case_id,
                {
                    "decision": decision,
                    "actor": actor,
                    "authorization_decision_id": authorization_decision_id,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    with connect() as conn:
        row = conn.execute("SELECT * FROM scheme_certification_cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        raise SovereignError("certification case disappeared after decision")
    return _certification_case_public(dict(row))


def _currency_code(value: str) -> str:
    currency = str(value or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise SovereignError("currency must be an explicit three-letter code")
    return currency


def _expiry(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SovereignError("QR expiry must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise SovereignError("QR expiry must include a timezone")
    return parsed.astimezone(timezone.utc)


def create_qr_record(
    participant_id: str,
    merchant_ref: str,
    alias: str,
    currency: str,
    *,
    amount_minor: int | None = None,
    expires_at: str | None = None,
    profile_key: str = "generic",
    scheme_profile_id: str | None = None,
    channel: str = "pos",
) -> dict:
    participant_id = str(participant_id or "").strip()
    merchant_ref = str(merchant_ref or "").strip()
    normalized_alias = str(alias or "").strip().lower()
    currency = _currency_code(currency)
    profile_key = str(profile_key or "generic").strip().lower()
    scheme_profile_id = str(scheme_profile_id or "").strip() or None
    channel = str(channel or "pos").strip().lower()
    if not participant_id:
        raise SovereignError("scheme participant is required")
    if not merchant_ref:
        raise SovereignError("merchant reference is required")
    if not profile_key:
        raise SovereignError("QR profile key is required")
    if not channel:
        raise SovereignError("QR channel is required")
    if amount_minor is not None and int(amount_minor) <= 0:
        raise SovereignError("dynamic QR amount must be positive")
    expiry = _expiry(expires_at)

    resolved = resolve_payment_alias(normalized_alias)
    if not resolved:
        raise SovereignError("QR alias is not resolvable")
    if resolved["participant_id"] != participant_id:
        raise SovereignError("QR alias does not belong to participant")

    qr_id = f"sqr_{uuid.uuid4().hex}"
    nonce = uuid.uuid4().hex
    created_at = now_iso()
    stored_expiry = expiry.isoformat() if expiry is not None else None

    if profile_key == "zimbabwe-2026":
        if amount_minor is None:
            raise SovereignError("Zimbabwe profile requires dynamic QR amount")
        if expiry is None:
            raise SovereignError("Zimbabwe profile requires QR expiry")
        if expiry <= datetime.now(timezone.utc):
            raise SovereignError("Zimbabwe profile QR expiry must be in the future")
        if not scheme_profile_id:
            raise SovereignError("Zimbabwe profile requires a registered scheme profile")
        with connect() as conn:
            scheme_profile = conn.execute(
                "SELECT * FROM qr_scheme_profiles WHERE id=? AND profile_key=?",
                (scheme_profile_id, profile_key),
            ).fetchone()
        if not scheme_profile:
            raise SovereignError("Zimbabwe scheme profile is not registered")
        point_of_initiation_method = "12"
        reference_tag_62_05 = nonce
        serialization_status = "normalized_not_emvco_certified"
    else:
        if scheme_profile_id:
            raise SovereignError("scheme profile id is only supported by an explicit QR profile")
        point_of_initiation_method = "12" if amount_minor is not None else "11"
        reference_tag_62_05 = nonce if amount_minor is not None else None
        serialization_status = "internal_reference"

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """INSERT INTO scheme_qr_records
                   (id,participant_id,merchant_ref,alias,currency,amount_minor,nonce,expires_at,
                    profile_key,scheme_profile_id,channel,point_of_initiation_method,
                    reference_tag_62_05,serialization_status,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    qr_id,
                    participant_id,
                    merchant_ref,
                    normalized_alias,
                    currency,
                    int(amount_minor) if amount_minor is not None else None,
                    nonce,
                    stored_expiry,
                    profile_key,
                    scheme_profile_id,
                    channel,
                    point_of_initiation_method,
                    reference_tag_62_05,
                    serialization_status,
                    created_at,
                ),
            )
            append_audit(
                "sovereign.qr_created",
                qr_id,
                {
                    "participant_id": participant_id,
                    "merchant_ref": merchant_ref,
                    "alias": normalized_alias,
                    "currency": currency,
                    "amount_minor": int(amount_minor) if amount_minor is not None else None,
                    "expires_at": stored_expiry,
                    "profile_key": profile_key,
                    "scheme_profile_id": scheme_profile_id,
                    "channel": channel,
                    "point_of_initiation_method": point_of_initiation_method,
                    "reference_tag_62_05": reference_tag_62_05,
                    "serialization_status": serialization_status,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return {
        "id": qr_id,
        "participant_id": participant_id,
        "merchant_ref": merchant_ref,
        "alias": normalized_alias,
        "currency": currency,
        "amount_minor": int(amount_minor) if amount_minor is not None else None,
        "nonce": nonce,
        "expires_at": stored_expiry,
        "profile_key": profile_key,
        "scheme_profile_id": scheme_profile_id,
        "channel": channel,
        "point_of_initiation_method": point_of_initiation_method,
        "reference_tag_62_05": reference_tag_62_05,
        "serialization_status": serialization_status,
        "created_at": created_at,
    }


def resolve_qr_record(qr_id: str, nonce: str) -> dict | None:
    qr_id = str(qr_id or "").strip()
    nonce = str(nonce or "").strip()
    if not qr_id or not nonce:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM scheme_qr_records WHERE id=? AND nonce=?",
            (qr_id, nonce),
        ).fetchone()
    if not row:
        return None
    record = dict(row)
    expiry = _expiry(record.get("expires_at"))
    if expiry is not None and datetime.now(timezone.utc) >= expiry:
        return None
    if resolve_payment_alias(record["alias"]) is None:
        return None
    if record.get("profile_key") == "zimbabwe-2026":
        scheme_profile_id = str(record.get("scheme_profile_id") or "").strip()
        if not scheme_profile_id:
            return None
        with connect() as conn:
            scheme_profile = conn.execute(
                "SELECT id FROM qr_scheme_profiles WHERE id=? AND profile_key='zimbabwe-2026'",
                (scheme_profile_id,),
            ).fetchone()
        if not scheme_profile:
            return None
    return record


def _request_hash(
    *,
    payee_alias: str,
    payer_alias: str,
    amount_minor: int,
    currency: str,
    reference: str,
) -> str:
    payload = {
        "payee_alias": payee_alias,
        "payer_alias": payer_alias,
        "amount_minor": int(amount_minor),
        "currency": currency,
        "reference": reference,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_to_pay_public(row: dict) -> dict:
    result = {
        "id": row["id"],
        "payee_alias": row["payee_alias"],
        "payer_alias": row["payer_alias"],
        "amount_minor": int(row["amount_minor"]),
        "currency": row["currency"],
        "reference": row["reference"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if row["status"] == "accepted":
        result["payment_instruction"] = {
            "request_to_pay_id": row["id"],
            "payer_alias": row["payer_alias"],
            "payee_alias": row["payee_alias"],
            "amount_minor": int(row["amount_minor"]),
            "currency": row["currency"],
            "reference": row["reference"],
        }
    return result


def create_request_to_pay(
    payee_alias: str,
    payer_alias: str,
    amount_minor: int,
    currency: str,
    reference: str,
    idempotency_key: str,
) -> dict:
    payee_alias = str(payee_alias or "").strip().lower()
    payer_alias = str(payer_alias or "").strip().lower()
    reference = str(reference or "").strip()
    idempotency_key = str(idempotency_key or "").strip()
    currency = _currency_code(currency)
    amount_minor = int(amount_minor)

    if amount_minor <= 0:
        raise SovereignError("request-to-pay amount must be positive")
    if not reference:
        raise SovereignError("request-to-pay reference is required")
    if not idempotency_key:
        raise SovereignError("request-to-pay idempotency key is required")
    if resolve_payment_alias(payee_alias) is None:
        raise SovereignError("request-to-pay payee alias is not resolvable")
    if resolve_payment_alias(payer_alias) is None:
        raise SovereignError("request-to-pay payer alias is not resolvable")

    request_hash = _request_hash(
        payee_alias=payee_alias,
        payer_alias=payer_alias,
        amount_minor=amount_minor,
        currency=currency,
        reference=reference,
    )
    request_id = f"rtp_{uuid.uuid4().hex}"
    ts = now_iso()

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT * FROM request_to_pay WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                existing = dict(existing)
                if existing["request_hash"] != request_hash:
                    raise SovereignError("request-to-pay idempotency key conflicts with a different request")
                conn.execute("COMMIT")
                return _request_to_pay_public(existing)

            conn.execute(
                """INSERT INTO request_to_pay
                   (id,idempotency_key,request_hash,payee_alias,payer_alias,amount_minor,currency,reference,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    request_id,
                    idempotency_key,
                    request_hash,
                    payee_alias,
                    payer_alias,
                    amount_minor,
                    currency,
                    reference,
                    "pending",
                    ts,
                    ts,
                ),
            )
            append_audit(
                "sovereign.request_to_pay_created",
                request_id,
                {
                    "payee_alias": payee_alias,
                    "payer_alias": payer_alias,
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "reference": reference,
                    "idempotency_key": idempotency_key,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    return _request_to_pay_public({
        "id": request_id,
        "payee_alias": payee_alias,
        "payer_alias": payer_alias,
        "amount_minor": amount_minor,
        "currency": currency,
        "reference": reference,
        "status": "pending",
        "created_at": ts,
        "updated_at": ts,
    })


def respond_request_to_pay(request_id: str, decision: str, actor_alias: str) -> dict:
    request_id = str(request_id or "").strip()
    decision = str(decision or "").strip().lower()
    actor_alias = str(actor_alias or "").strip().lower()
    if decision not in {"accepted", "declined", "cancelled"}:
        raise SovereignError("unsupported request-to-pay decision")
    if not actor_alias:
        raise SovereignError("request-to-pay actor alias is required")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM request_to_pay WHERE id=?",
                (request_id,),
            ).fetchone()
            if not row:
                raise SovereignError("request-to-pay not found")
            current = dict(row)
            if current["status"] != "pending":
                raise SovereignError("request-to-pay is already terminal")

            if decision in {"accepted", "declined"}:
                expected_actor = current["payer_alias"]
                if actor_alias != expected_actor:
                    raise SovereignError("only payer alias may accept or decline request-to-pay")
            else:
                expected_actor = current["payee_alias"]
                if actor_alias != expected_actor:
                    raise SovereignError("only payee alias may cancel request-to-pay")

            if resolve_payment_alias(actor_alias) is None:
                raise SovereignError("request-to-pay actor alias is not currently resolvable")

            ts = now_iso()
            updated = conn.execute(
                "UPDATE request_to_pay SET status=?,updated_at=? WHERE id=? AND status='pending'",
                (decision, ts, request_id),
            )
            if updated.rowcount != 1:
                raise SovereignError("request-to-pay state changed before response commit")
            append_audit(
                "sovereign.request_to_pay_responded",
                request_id,
                {
                    "decision": decision,
                    "actor_alias": actor_alias,
                    "previous_status": "pending",
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    with connect() as conn:
        result = conn.execute(
            "SELECT * FROM request_to_pay WHERE id=?",
            (request_id,),
        ).fetchone()
    if not result:
        raise SovereignError("request-to-pay disappeared after response")
    return _request_to_pay_public(dict(result))
