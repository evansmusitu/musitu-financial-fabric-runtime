from __future__ import annotations

from .audit import append_audit, now_iso
from .config import settings
from .db import connect
from .ledger import post
from .production import assert_live_funds_allowed


class ProviderSettlementError(RuntimeError):
    pass


def _payment(payment_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM payment_intents WHERE id=?", (payment_id,)).fetchone()
    if not row:
        raise ProviderSettlementError("payment not found")
    return dict(row)


def _rail_account(rail: str, currency: str) -> dict:
    from .ledger import create_account
    return create_account("system", rail, currency, "rail_clearing")


def provider_succeed(*, provider: str, payment_id: str, provider_event_id: str) -> dict:
    if not settings.is_production:
        from .service import settle_payment
        return settle_payment(payment_id, provider_event_id)
    assert_live_funds_allowed()
    payment = _payment(payment_id)
    if payment["rail"] != provider:
        raise ProviderSettlementError("provider does not match payment rail")
    if payment["status"] == "succeeded":
        return payment
    if payment["status"] in {"failed", "cancelled", "refunded"}:
        raise ProviderSettlementError(f"cannot settle payment in status {payment['status']}")
    rail_account = _rail_account(payment["rail"], payment["currency"])
    post(
        reference=f"payment:{payment_id}",
        memo=f"Provider settlement {payment['rail']} payment {payment_id}",
        postings=[
            (rail_account["id"], -int(payment["amount_minor"])),
            (payment["destination_account_id"], int(payment["amount_minor"])),
        ],
    )
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                "UPDATE payment_intents SET status='succeeded',updated_at=? WHERE id=? AND status NOT IN ('failed','cancelled','refunded')",
                (now_iso(), payment_id),
            )
            if updated.rowcount != 1:
                raise ProviderSettlementError("payment state changed before settlement commit")
            append_audit("payment.provider_succeeded", payment_id, {
                "provider": provider, "provider_event_id": provider_event_id,
            }, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return _payment(payment_id)


def provider_fail(*, provider: str, payment_id: str, provider_event_id: str) -> dict:
    if not settings.is_production:
        from .service import fail_payment
        return fail_payment(payment_id, provider_event_id)
    assert_live_funds_allowed()
    payment = _payment(payment_id)
    if payment["rail"] != provider:
        raise ProviderSettlementError("provider does not match payment rail")
    if payment["status"] == "failed":
        return payment
    if payment["status"] == "succeeded":
        raise ProviderSettlementError("cannot fail a succeeded payment")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                "UPDATE payment_intents SET status='failed',updated_at=? WHERE id=? AND status!='succeeded'",
                (now_iso(), payment_id),
            )
            if updated.rowcount != 1:
                raise ProviderSettlementError("payment state changed before failure commit")
            append_audit("payment.provider_failed", payment_id, {
                "provider": provider, "provider_event_id": provider_event_id,
            }, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return _payment(payment_id)
