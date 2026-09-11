from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .audit import append_audit, now_iso
from .db import connect


class WebhookReplayConflict(RuntimeError):
    pass


_PROCESSING_LEASE = timedelta(seconds=60)
_SUCCESS_STATUSES = {"succeeded", "success", "paid", "completed"}
_FAILURE_STATUSES = {"failed", "declined", "cancelled", "canceled"}
_TERMINAL_PAYMENT_STATES = {"succeeded", "failed", "cancelled", "canceled", "refunded"}


def _ensure_delivery_table() -> None:
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS webhook_delivery_state (
                event_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                payment_id TEXT NOT NULL,
                target_status TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT
            )"""
        )


def _parse_terminal_event(body: bytes) -> tuple[str, str, str] | None:
    try:
        payload = json.loads(body)
        event_id = str(payload["event_id"]).strip()
        payment_id = str(payload["payment_id"]).strip()
        status = str(payload["status"]).strip().lower()
    except Exception:
        return None
    if not event_id or not payment_id:
        return None
    if status in _SUCCESS_STATUSES:
        return event_id, payment_id, "succeeded"
    if status in _FAILURE_STATUSES:
        return event_id, payment_id, "failed"
    return None


def _is_stale(updated_at: str) -> bool:
    try:
        stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return datetime.now(timezone.utc) - stamp >= _PROCESSING_LEASE


def begin_webhook_delivery(provider: str, body: bytes) -> str:
    """Acquire a durable processing lease for a terminal provider event.

    Returns one of: passthrough, process, inflight, processed.
    The compatibility webhook receipt is removed only when a failed/stale event is
    deliberately reopened so the existing endpoint can re-register and execute it.
    """
    parsed = _parse_terminal_event(body)
    if parsed is None:
        return "passthrough"
    event_id, payment_id, target_status = parsed
    digest = hashlib.sha256(body).hexdigest()
    provider = provider.strip().lower()
    if not provider:
        raise WebhookReplayConflict("webhook provider is missing")

    _ensure_delivery_table()
    ts = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            payment = conn.execute(
                "SELECT status,rail FROM payment_intents WHERE id=?",
                (payment_id,),
            ).fetchone()
            if not payment or str(payment["rail"]).lower() != provider:
                conn.execute("COMMIT")
                return "passthrough"

            receipt = conn.execute(
                "SELECT provider,payload_hash FROM webhook_events WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if receipt and (
                str(receipt["provider"]).lower() != provider
                or str(receipt["payload_hash"]) != digest
            ):
                raise WebhookReplayConflict("webhook event id conflicts with an existing receipt payload")

            inserted = conn.execute(
                """INSERT INTO webhook_delivery_state
                   (event_id,provider,payload_hash,payment_id,target_status,state,attempts,started_at,updated_at,last_error)
                   VALUES (?,?,?,?,?,'processing',1,?,?,NULL)
                   ON CONFLICT(event_id) DO NOTHING""",
                (event_id, provider, digest, payment_id, target_status, ts, ts),
            )
            if inserted.rowcount == 1:
                append_audit(
                    "webhook.delivery_started",
                    event_id,
                    {"provider": provider, "payment_id": payment_id, "target_status": target_status, "payload_hash": digest},
                    conn=conn,
                )
                conn.execute("COMMIT")
                return "process"

            row = conn.execute(
                "SELECT * FROM webhook_delivery_state WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if not row:
                raise WebhookReplayConflict("webhook delivery state disappeared")
            if (
                str(row["provider"]).lower() != provider
                or row["payload_hash"] != digest
                or row["payment_id"] != payment_id
                or row["target_status"] != target_status
            ):
                raise WebhookReplayConflict("webhook event id conflicts with a different payload")

            current = str(payment["status"]).lower()
            if current == target_status:
                conn.execute(
                    "UPDATE webhook_delivery_state SET state='processed',updated_at=?,last_error=NULL WHERE event_id=?",
                    (ts, event_id),
                )
                append_audit(
                    "webhook.delivery_reconciled",
                    event_id,
                    {"provider": provider, "payment_id": payment_id, "target_status": target_status},
                    conn=conn,
                )
                conn.execute("COMMIT")
                return "processed"
            if current in _TERMINAL_PAYMENT_STATES and current != target_status:
                raise WebhookReplayConflict(
                    f"webhook target {target_status} conflicts with terminal payment state {current}"
                )

            state = str(row["state"]).lower()
            if state == "processed":
                conn.execute("COMMIT")
                return "processed"
            if state == "processing" and not _is_stale(str(row["updated_at"])):
                conn.execute("COMMIT")
                return "inflight"

            conn.execute(
                "DELETE FROM webhook_events WHERE event_id=? AND provider=? AND payload_hash=?",
                (event_id, provider, digest),
            )
            conn.execute(
                """UPDATE webhook_delivery_state
                   SET state='processing',attempts=attempts+1,started_at=?,updated_at=?,last_error=NULL
                   WHERE event_id=?""",
                (ts, ts, event_id),
            )
            append_audit(
                "webhook.delivery_retried",
                event_id,
                {"provider": provider, "payment_id": payment_id, "target_status": target_status},
                conn=conn,
            )
            conn.execute("COMMIT")
            return "process"
        except Exception:
            conn.execute("ROLLBACK")
            raise


def finish_webhook_delivery(provider: str, body: bytes, response_status: int) -> None:
    parsed = _parse_terminal_event(body)
    if parsed is None:
        return
    event_id, payment_id, target_status = parsed
    digest = hashlib.sha256(body).hexdigest()
    provider = provider.strip().lower()
    _ensure_delivery_table()
    ts = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM webhook_delivery_state WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return
            if (
                str(row["provider"]).lower() != provider
                or row["payload_hash"] != digest
                or row["payment_id"] != payment_id
                or row["target_status"] != target_status
            ):
                raise WebhookReplayConflict("webhook delivery completion conflicts with stored event")

            if 200 <= int(response_status) < 300:
                state = "processed"
                last_error = None
                event_type = "webhook.delivery_processed"
            else:
                state = "failed"
                last_error = f"http_status={int(response_status)}"
                event_type = "webhook.delivery_failed"
            conn.execute(
                "UPDATE webhook_delivery_state SET state=?,updated_at=?,last_error=? WHERE event_id=?",
                (state, ts, last_error, event_id),
            )
            append_audit(
                event_type,
                event_id,
                {"provider": provider, "payment_id": payment_id, "target_status": target_status, "response_status": int(response_status)},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
