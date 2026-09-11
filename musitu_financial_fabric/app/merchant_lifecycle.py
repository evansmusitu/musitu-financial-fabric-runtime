from __future__ import annotations

from .audit import append_audit
from .config import settings
from .db import connect


class MerchantLifecycleError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS = {
    "pending_review": {"active", "rejected"},
    "active": {"suspended"},
    "suspended": {"active", "rejected"},
    "sandbox": {"active", "rejected"},
}


def review_merchant(
    *,
    merchant_id: str,
    target_status: str,
    evidence_ref: str,
    actor: str,
    authorization_decision_id: str,
) -> dict:
    """Apply an evidence-referenced merchant lifecycle decision.

    Production callers are authenticated and authorized by middleware before
    reaching this function.  The actor and authorization decision are copied
    into the chained audit record so merchant activation never requires an
    unaudited database mutation.
    """
    target_status = target_status.strip().lower()
    evidence_ref = evidence_ref.strip()
    actor = actor.strip()
    authorization_decision_id = authorization_decision_id.strip()

    if target_status not in {"active", "suspended", "rejected"}:
        raise MerchantLifecycleError("unsupported merchant target status")
    if not evidence_ref:
        raise MerchantLifecycleError("merchant review evidence reference is required")
    if settings.is_production and not actor:
        raise MerchantLifecycleError("production merchant review actor is required")
    if settings.is_production and not authorization_decision_id:
        raise MerchantLifecycleError("production authorization decision id is required")

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM merchants WHERE id=?", (merchant_id,)).fetchone()
            if not row:
                raise MerchantLifecycleError("merchant not found")
            merchant = dict(row)
            current = str(merchant["status"])
            if current == target_status:
                conn.execute("COMMIT")
                return merchant
            if target_status not in _ALLOWED_TRANSITIONS.get(current, set()):
                raise MerchantLifecycleError(f"merchant transition {current}->{target_status} is not allowed")

            updated = conn.execute(
                "UPDATE merchants SET status=? WHERE id=? AND status=?",
                (target_status, merchant_id, current),
            )
            if updated.rowcount != 1:
                raise MerchantLifecycleError("merchant state changed before review commit")
            append_audit(
                "merchant.reviewed",
                merchant_id,
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
        result = conn.execute("SELECT * FROM merchants WHERE id=?", (merchant_id,)).fetchone()
    if not result:
        raise MerchantLifecycleError("merchant disappeared after review")
    return dict(result)
