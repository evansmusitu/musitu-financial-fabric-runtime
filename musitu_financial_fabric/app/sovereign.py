from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .audit import append_audit, now_iso
from .config import settings
from .db import connect


class SovereignError(RuntimeError):
    pass


PARTICIPANT_TYPES = {"bank", "mobile_money", "fintech", "government", "switch", "psp"}
ALIAS_TYPES = {"phone", "email", "vpa", "merchant", "account"}

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
) -> dict:
    participant_id = str(participant_id or "").strip()
    merchant_ref = str(merchant_ref or "").strip()
    normalized_alias = str(alias or "").strip().lower()
    currency = _currency_code(currency)
    if not participant_id:
        raise SovereignError("scheme participant is required")
    if not merchant_ref:
        raise SovereignError("merchant reference is required")
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
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """INSERT INTO scheme_qr_records
                   (id,participant_id,merchant_ref,alias,currency,amount_minor,nonce,expires_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    qr_id,
                    participant_id,
                    merchant_ref,
                    normalized_alias,
                    currency,
                    int(amount_minor) if amount_minor is not None else None,
                    nonce,
                    stored_expiry,
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
    return record
