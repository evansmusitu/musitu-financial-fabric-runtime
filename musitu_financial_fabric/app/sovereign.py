from __future__ import annotations

import uuid

from .audit import append_audit, now_iso
from .config import settings
from .db import connect


class SovereignError(RuntimeError):
    pass


PARTICIPANT_TYPES = {"bank", "mobile_money", "fintech", "government", "switch", "psp"}
ALIAS_TYPES = {"phone", "email", "vpa", "merchant", "account"}


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
