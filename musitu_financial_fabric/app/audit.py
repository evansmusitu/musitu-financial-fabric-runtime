from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .db import connect


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def append_audit(event_type: str, entity_id: str, body: dict[str, Any], conn=None) -> str:
    own_conn = conn is None
    if own_conn:
        ctx = connect()
        conn = ctx.__enter__()
    started_transaction = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            started_transaction = True
        if settings.uses_postgres:
            # Serialize the hash-chain head across concurrent writers.
            conn.execute("SELECT pg_advisory_xact_lock(736588191)")
        row = conn.execute("SELECT event_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = row["event_hash"] if row else "GENESIS"
        body_json = json.dumps(body, sort_keys=True, separators=(",", ":"))
        created_at = now_iso()
        event_hash = _hash("|".join([prev_hash, event_type, entity_id, body_json, created_at]))
        conn.execute(
            "INSERT INTO audit_log(event_type,entity_id,body_json,prev_hash,event_hash,created_at) VALUES (?,?,?,?,?,?)",
            (event_type, entity_id, body_json, prev_hash, event_hash, created_at),
        )
        if started_transaction:
            conn.execute("COMMIT")
        return event_hash
    except Exception:
        if started_transaction and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        if own_conn:
            ctx.__exit__(None, None, None)


def verify_audit_chain() -> tuple[bool, int, str | None]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM audit_log ORDER BY seq").fetchall()
    prev = "GENESIS"
    for row in rows:
        expected = _hash("|".join([prev, row["event_type"], row["entity_id"], row["body_json"], row["created_at"]]))
        if row["prev_hash"] != prev or row["event_hash"] != expected:
            return False, len(rows), str(row["seq"])
        prev = row["event_hash"]
    return True, len(rows), None
