from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from .audit import append_audit, now_iso
from .db import connect
from .sovereign import (
    COUNTRY_PROFILE_DEPENDENCIES,
    SovereignError,
    set_country_profile_dependency,
)


class SovereignEvidenceError(RuntimeError):
    pass


EVIDENCE_STATUSES = {"registered", "externally_verified", "revoked"}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _required(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise SovereignEvidenceError(f"{label} is required")
    return normalized


def _canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_scope(profile_key: str, dependency_key: str) -> tuple[str, str]:
    profile_key = _required(profile_key, "profile key").lower()
    dependency_key = _required(dependency_key, "dependency key").lower()
    required = COUNTRY_PROFILE_DEPENDENCIES.get(profile_key)
    if not required:
        raise SovereignEvidenceError("unsupported country profile")
    if dependency_key not in required:
        raise SovereignEvidenceError("unsupported country profile dependency")
    return profile_key, dependency_key


def _validate_sha256(value: str) -> str:
    normalized = _required(value, "source sha-256").lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise SovereignEvidenceError("source sha-256 must be exactly 64 hexadecimal characters")
    return normalized


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_key": row["profile_key"],
        "dependency_key": row["dependency_key"],
        "evidence_ref": row["evidence_ref"],
        "source_authority": row["source_authority"],
        "source_version": row["source_version"],
        "source_location": row["source_location"],
        "source_sha256": row["source_sha256"],
        "status": row["status"],
        "registered_by": row["registered_by"],
        "registered_at": row["registered_at"],
        "verified_by": row.get("verified_by"),
        "verification_authorization_decision_id": row.get(
            "verification_authorization_decision_id"
        ),
        "verified_at": row.get("verified_at"),
        "revoked_by": row.get("revoked_by"),
        "revocation_authorization_decision_id": row.get(
            "revocation_authorization_decision_id"
        ),
        "revocation_reason": row.get("revocation_reason"),
        "revoked_at": row.get("revoked_at"),
        "payload_hash": row["payload_hash"],
    }


def _load(record_id: str) -> dict[str, Any]:
    record_id = _required(record_id, "evidence record id")
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM country_profile_evidence_records WHERE id=?",
            (record_id,),
        ).fetchone()
    if not row:
        raise SovereignEvidenceError("evidence record not found")
    return dict(row)


def register_country_profile_evidence(
    profile_key: str,
    dependency_key: str,
    *,
    evidence_ref: str,
    source_authority: str,
    source_version: str,
    source_location: str,
    source_sha256: str,
    actor: str,
) -> dict[str, Any]:
    profile_key, dependency_key = _validate_scope(profile_key, dependency_key)
    evidence_ref = _required(evidence_ref, "evidence reference")
    source_authority = _required(source_authority, "source authority")
    source_version = _required(source_version, "source version")
    source_location = _required(source_location, "source location")
    source_sha256 = _validate_sha256(source_sha256)
    actor = _required(actor, "evidence registration actor")

    payload = {
        "profile_key": profile_key,
        "dependency_key": dependency_key,
        "evidence_ref": evidence_ref,
        "source_authority": source_authority,
        "source_version": source_version,
        "source_location": source_location,
        "source_sha256": source_sha256,
        "registered_by": actor,
    }
    payload_hash = _canonical_hash(payload)
    record_id = f"cpe_{uuid.uuid4().hex}"
    ts = now_iso()

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT * FROM country_profile_evidence_records WHERE evidence_ref=?",
                (evidence_ref,),
            ).fetchone()
            if existing:
                existing_dict = dict(existing)
                if str(existing_dict["payload_hash"]) != payload_hash:
                    raise SovereignEvidenceError(
                        "conflicting reuse of evidence reference"
                    )
                conn.execute("COMMIT")
                return _public(existing_dict)

            conn.execute(
                """INSERT INTO country_profile_evidence_records
                   (id,profile_key,dependency_key,evidence_ref,source_authority,
                    source_version,source_location,source_sha256,status,registered_by,
                    registered_at,payload_hash)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id,
                    profile_key,
                    dependency_key,
                    evidence_ref,
                    source_authority,
                    source_version,
                    source_location,
                    source_sha256,
                    "registered",
                    actor,
                    ts,
                    payload_hash,
                ),
            )
            append_audit(
                "sovereign.country_profile_evidence_registered",
                record_id,
                {
                    "profile_key": profile_key,
                    "dependency_key": dependency_key,
                    "evidence_ref": evidence_ref,
                    "source_authority": source_authority,
                    "source_version": source_version,
                    "source_location": source_location,
                    "source_sha256": source_sha256,
                    "payload_hash": payload_hash,
                    "actor": actor,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    return _public(_load(record_id))


def verify_country_profile_evidence(
    record_id: str,
    *,
    actor: str,
    authorization_decision_id: str,
) -> dict[str, Any]:
    actor = _required(actor, "evidence verification actor")
    authorization_decision_id = _required(
        authorization_decision_id, "evidence verification authorization decision"
    )

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM country_profile_evidence_records WHERE id=?",
                (_required(record_id, "evidence record id"),),
            ).fetchone()
            if not row:
                raise SovereignEvidenceError("evidence record not found")
            current = dict(row)
            status = str(current["status"])
            if status == "revoked":
                raise SovereignEvidenceError("revoked evidence cannot be verified")
            if status == "externally_verified":
                conn.execute("COMMIT")
                return _public(current)

            ts = now_iso()
            conn.execute(
                """UPDATE country_profile_evidence_records
                   SET status='externally_verified',verified_by=?,
                       verification_authorization_decision_id=?,verified_at=?
                   WHERE id=?""",
                (actor, authorization_decision_id, ts, current["id"]),
            )
            append_audit(
                "sovereign.country_profile_evidence_verified",
                str(current["id"]),
                {
                    "profile_key": current["profile_key"],
                    "dependency_key": current["dependency_key"],
                    "source_authority": current["source_authority"],
                    "source_version": current["source_version"],
                    "source_sha256": current["source_sha256"],
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

    return _public(_load(record_id))


def revoke_country_profile_evidence(
    record_id: str,
    *,
    actor: str,
    authorization_decision_id: str,
    reason: str,
) -> dict[str, Any]:
    actor = _required(actor, "evidence revocation actor")
    authorization_decision_id = _required(
        authorization_decision_id, "evidence revocation authorization decision"
    )
    reason = _required(reason, "evidence revocation reason")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM country_profile_evidence_records WHERE id=?",
                (_required(record_id, "evidence record id"),),
            ).fetchone()
            if not row:
                raise SovereignEvidenceError("evidence record not found")
            current = dict(row)
            if str(current["status"]) == "revoked":
                same = (
                    str(current.get("revoked_by") or "") == actor
                    and str(
                        current.get("revocation_authorization_decision_id") or ""
                    )
                    == authorization_decision_id
                    and str(current.get("revocation_reason") or "") == reason
                )
                if not same:
                    raise SovereignEvidenceError(
                        "conflicting evidence revocation replay"
                    )
                conn.execute("COMMIT")
                return _public(current)

            ts = now_iso()
            conn.execute(
                """UPDATE country_profile_evidence_records
                   SET status='revoked',revoked_by=?,
                       revocation_authorization_decision_id=?,revocation_reason=?,
                       revoked_at=?
                   WHERE id=?""",
                (
                    actor,
                    authorization_decision_id,
                    reason,
                    ts,
                    current["id"],
                ),
            )
            append_audit(
                "sovereign.country_profile_evidence_revoked",
                str(current["id"]),
                {
                    "profile_key": current["profile_key"],
                    "dependency_key": current["dependency_key"],
                    "source_sha256": current["source_sha256"],
                    "actor": actor,
                    "authorization_decision_id": authorization_decision_id,
                    "reason": reason,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    binding = (
        f"evidence-record:{current['id']}:sha256:{current['source_sha256']}"
    )
    with connect() as conn:
        dependency = conn.execute(
            """SELECT * FROM country_profile_dependencies
               WHERE profile_key=? AND dependency_key=?""",
            (current["profile_key"], current["dependency_key"]),
        ).fetchone()
    if dependency and str(dependency["evidence_ref"] or "") == binding:
        set_country_profile_dependency(
            str(current["profile_key"]),
            str(current["dependency_key"]),
            "reference",
            evidence_ref=(
                f"revoked-evidence-record:{current['id']}:"
                f"sha256:{current['source_sha256']}"
            ),
            actor=actor,
            authorization_decision_id=authorization_decision_id,
        )

    return _public(_load(record_id))


def promote_country_profile_dependency_from_evidence(
    profile_key: str,
    dependency_key: str,
    record_id: str,
    *,
    actor: str,
    authorization_decision_id: str,
) -> dict[str, Any]:
    profile_key, dependency_key = _validate_scope(profile_key, dependency_key)
    actor = _required(actor, "dependency promotion actor")
    authorization_decision_id = _required(
        authorization_decision_id, "dependency promotion authorization decision"
    )
    record = _load(record_id)

    if str(record["profile_key"]) != profile_key:
        raise SovereignEvidenceError("evidence record profile does not match")
    if str(record["dependency_key"]) != dependency_key:
        raise SovereignEvidenceError("evidence record dependency does not match")
    if str(record["status"]) != "externally_verified":
        raise SovereignEvidenceError(
            "evidence record must be externally verified before promotion"
        )

    binding = f"evidence-record:{record['id']}:sha256:{record['source_sha256']}"
    try:
        promoted = set_country_profile_dependency(
            profile_key,
            dependency_key,
            "externally_verified",
            evidence_ref=binding,
            actor=actor,
            authorization_decision_id=authorization_decision_id,
        )
    except SovereignError as exc:
        raise SovereignEvidenceError(str(exc)) from exc

    return {
        **promoted,
        "evidence_record_id": record["id"],
        "source_sha256": record["source_sha256"],
        "source_authority": record["source_authority"],
        "source_version": record["source_version"],
        "source_location": record["source_location"],
    }
