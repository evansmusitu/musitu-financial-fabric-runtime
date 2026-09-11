from __future__ import annotations

import hashlib
import json
import uuid

from .audit import append_audit, now_iso
from .config import settings
from .db import connect
from .ledger import create_account, post
from .mandates import AgentMandate, authorize_mandate
from .policy import evaluate_payment_policy
from .rails.base import RailRequest
from .rails.ecocash import EcoCashRail
from .rails.generic import ConfiguredExternalRail
from .rails.internal import InternalRail
from .risk import evaluate_reference_risk
from .router import choose_route, score_route


RAILS = {
    "ecocash": EcoCashRail(),
    "internal": InternalRail(),
    "bank": ConfiguredExternalRail("bank"),
    "card": ConfiguredExternalRail("card"),
    "stablecoin": ConfiguredExternalRail("stablecoin"),
}


class PaymentError(RuntimeError):
    pass


def _require_sandbox_for_manual_state_change() -> None:
    if settings.environment == "production":
        raise PaymentError("manual payment state changes are disabled in production")


def create_identity(kind: str, display_name: str) -> dict:
    if kind not in {"human", "business", "agent", "device", "institution"}:
        raise PaymentError("unsupported identity kind")
    identity_id = f"idn_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO identities(id,kind,display_name,status,created_at) VALUES (?,?,?,?,?)",
            (identity_id, kind, display_name, "active", created_at),
        )
        append_audit("identity.created", identity_id, {"kind": kind, "display_name": display_name}, conn=conn)
    return {"id": identity_id, "kind": kind, "display_name": display_name, "status": "active", "created_at": created_at}


def create_agent_mandate(*, principal_id: str, agent_id: str, max_per_payment_minor: int, max_daily_minor: int, currency: str, allowed_rails: list[str]) -> dict:
    if max_per_payment_minor <= 0 or max_daily_minor < max_per_payment_minor:
        raise PaymentError("invalid mandate limits")
    if not allowed_rails or any(r not in RAILS for r in allowed_rails):
        raise PaymentError("invalid mandate rails")
    with connect() as conn:
        p = conn.execute("SELECT * FROM identities WHERE id=?", (principal_id,)).fetchone()
        a = conn.execute("SELECT * FROM identities WHERE id=?", (agent_id,)).fetchone()
        if not p or not a or a["kind"] != "agent":
            raise PaymentError("principal/agent identity invalid")
    mandate_id = f"mnd_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as conn:
        conn.execute(
            """INSERT INTO agent_mandates
               (id,principal_id,agent_id,max_per_payment_minor,max_daily_minor,currency,allowed_rails_json,status,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (mandate_id, principal_id, agent_id, max_per_payment_minor, max_daily_minor, currency.upper(), json.dumps(sorted(set(allowed_rails))), "active", created_at),
        )
        append_audit("agent_mandate.created", mandate_id, {"principal_id": principal_id, "agent_id": agent_id, "currency": currency.upper(), "allowed_rails": allowed_rails}, conn=conn)
    return get_agent_mandate(mandate_id)


def get_agent_mandate(mandate_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agent_mandates WHERE id=?", (mandate_id,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data["allowed_rails"] = json.loads(data.pop("allowed_rails_json"))
    return data


def _reserve_mandate_spend(*, mandate_id: str, amount_minor: int, currency: str, max_daily_minor: int, idempotency_key: str) -> bool:
    currency = currency.upper()
    ts = now_iso()
    day_utc = ts[:10]
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT * FROM agent_mandate_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if (
                    existing["mandate_id"] != mandate_id
                    or int(existing["amount_minor"]) != int(amount_minor)
                    or existing["currency"] != currency
                ):
                    raise PaymentError("idempotency key conflicts with an existing mandate reservation")
                if existing["status"] in {"reserved", "committed"}:
                    conn.execute("COMMIT")
                    return False
                if existing["status"] != "released":
                    raise PaymentError("mandate reservation is not reusable")

            used = conn.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS total
                   FROM agent_mandate_reservations
                   WHERE mandate_id=? AND day_utc=? AND status IN ('reserved','committed')""",
                (mandate_id, day_utc),
            ).fetchone()["total"]
            if int(used) + int(amount_minor) > int(max_daily_minor):
                raise PaymentError("mandate daily limit exceeded")

            if existing:
                conn.execute(
                    """UPDATE agent_mandate_reservations
                       SET day_utc=?,status='reserved',payment_id=NULL,updated_at=?
                       WHERE idempotency_key=?""",
                    (day_utc, ts, idempotency_key),
                )
            else:
                conn.execute(
                    """INSERT INTO agent_mandate_reservations
                       (idempotency_key,mandate_id,day_utc,amount_minor,currency,status,payment_id,created_at,updated_at)
                       VALUES (?,?,?,?,?,'reserved',NULL,?,?)""",
                    (idempotency_key, mandate_id, day_utc, int(amount_minor), currency, ts, ts),
                )
            append_audit(
                "agent_mandate.spend_reserved",
                mandate_id,
                {"idempotency_key": idempotency_key, "day_utc": day_utc, "amount_minor": int(amount_minor), "currency": currency},
                conn=conn,
            )
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _commit_mandate_spend(idempotency_key: str, payment_id: str) -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT mandate_id,status,payment_id FROM agent_mandate_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if not row:
                raise PaymentError("mandate spend reservation missing")
            if row["status"] == "committed":
                if row["payment_id"] != payment_id:
                    raise PaymentError("mandate spend reservation payment mismatch")
                conn.execute("COMMIT")
                return
            if row["status"] != "reserved":
                raise PaymentError("mandate spend reservation is not active")
            ts = now_iso()
            conn.execute(
                """UPDATE agent_mandate_reservations
                   SET status='committed',payment_id=?,updated_at=?
                   WHERE idempotency_key=?""",
                (payment_id, ts, idempotency_key),
            )
            append_audit(
                "agent_mandate.spend_committed",
                row["mandate_id"],
                {"idempotency_key": idempotency_key, "payment_id": payment_id},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _release_mandate_spend(idempotency_key: str) -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT mandate_id,status FROM agent_mandate_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if not row or row["status"] != "reserved":
                conn.execute("COMMIT")
                return
            ts = now_iso()
            conn.execute(
                "UPDATE agent_mandate_reservations SET status='released',updated_at=? WHERE idempotency_key=?",
                (ts, idempotency_key),
            )
            append_audit(
                "agent_mandate.spend_released",
                row["mandate_id"],
                {"idempotency_key": idempotency_key},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def create_merchant(name: str, currency: str) -> dict:
    merchant_id = f"mrc_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO merchants(id,name,status,created_at) VALUES (?,?,?,?)",
                (merchant_id, name, "sandbox" if settings.environment != "production" else "pending_review", created_at),
            )
            append_audit("merchant.created", merchant_id, {"name": name}, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    settlement = create_account("merchant", merchant_id, currency, "settlement")
    return {"id": merchant_id, "name": name, "status": "sandbox" if settings.environment != "production" else "pending_review", "settlement_account": settlement}


def get_or_create_rail_account(rail: str, currency: str) -> dict:
    return create_account("system", rail, currency, "rail_clearing")


def get_payment(payment_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM payment_intents WHERE id=?", (payment_id,)).fetchone()
    return dict(row) if row else None


def _payment_request_hash(*, merchant_id: str, destination_account_id: str, amount_minor: int, currency: str, requested_rail: str, payer_ref: str | None, description: str | None, callback_url: str | None) -> str:
    payload = {
        "merchant_id": merchant_id,
        "destination_account_id": destination_account_id,
        "amount_minor": int(amount_minor),
        "currency": currency.upper(),
        "requested_rail": requested_rail.lower(),
        "payer_ref": payer_ref,
        "description": description,
        "callback_url": callback_url,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _begin_payment_idempotency(*, idempotency_key: str, request_hash: str, merchant_id: str, destination_account_id: str, amount_minor: int, currency: str, requested_rail: str, payer_ref: str | None, description: str | None, callback_url: str | None) -> tuple[str, str | None]:
    ts = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            record = conn.execute(
                "SELECT * FROM payment_idempotency WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if record:
                if record["request_hash"] != request_hash:
                    raise PaymentError("idempotency key conflicts with a different payment request")
                if record["status"] == "committed":
                    if not record["payment_id"]:
                        raise PaymentError("committed idempotency record is missing payment reference")
                    conn.execute("COMMIT")
                    return "committed", str(record["payment_id"])
                if record["status"] == "reserved":
                    raise PaymentError("idempotent payment request is already in progress")
                raise PaymentError("idempotency record is not in a reusable state")

            legacy = conn.execute(
                "SELECT * FROM payment_intents WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if legacy:
                route_row = conn.execute(
                    "SELECT requested_rail FROM route_decisions WHERE payment_id=? ORDER BY id DESC LIMIT 1",
                    (legacy["id"],),
                ).fetchone()
                legacy_matches = (
                    legacy["merchant_id"] == merchant_id
                    and legacy["destination_account_id"] == destination_account_id
                    and int(legacy["amount_minor"]) == int(amount_minor)
                    and legacy["currency"] == currency.upper()
                    and legacy["payer_ref"] == payer_ref
                    and legacy["description"] == description
                    and route_row is not None
                    and route_row["requested_rail"] == requested_rail.lower()
                    and callback_url is None
                )
                if not legacy_matches:
                    raise PaymentError("idempotency key conflicts with a different legacy payment request")
                conn.execute("COMMIT")
                return "legacy", str(legacy["id"])

            conn.execute(
                """INSERT INTO payment_idempotency
                   (idempotency_key,request_hash,status,payment_id,created_at,updated_at)
                   VALUES (?,?,'reserved',NULL,?,?)""",
                (idempotency_key, request_hash, ts, ts),
            )
            append_audit(
                "payment.idempotency_reserved",
                idempotency_key,
                {"request_hash": request_hash},
                conn=conn,
            )
            conn.execute("COMMIT")
            return "reserved", None
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _payment_idempotency_reserved(idempotency_key: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT status FROM payment_idempotency WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
    return bool(row and row["status"] == "reserved")


def _release_payment_idempotency(idempotency_key: str, request_hash: str) -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT status,request_hash FROM payment_idempotency WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row and row["status"] == "reserved" and row["request_hash"] == request_hash:
                conn.execute("DELETE FROM payment_idempotency WHERE idempotency_key=?", (idempotency_key,))
                append_audit(
                    "payment.idempotency_released",
                    idempotency_key,
                    {"request_hash": request_hash, "reason": "no_external_dispatch"},
                    conn=conn,
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _persist_production_dispatch(*, payment_id: str, merchant_id: str, destination_account_id: str, amount_minor: int, currency: str, selected, requested_rail: str, payer_ref: str | None, description: str | None, idempotency_key: str, request_hash: str, risk_score: int, risk_decision_id: str, ts: str) -> None:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            lock_suffix = " FOR UPDATE" if settings.uses_postgres else ""
            merchant = conn.execute(
                "SELECT status FROM merchants WHERE id=?" + lock_suffix,
                (merchant_id,),
            ).fetchone()
            if not merchant or merchant["status"] != "active":
                raise PaymentError("merchant is not active at production dispatch claim")
            conn.execute(
                """INSERT INTO payment_intents
                (id,merchant_id,destination_account_id,amount_minor,currency,rail,payer_ref,description,status,external_reference,idempotency_key,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payment_id, merchant_id, destination_account_id, amount_minor, currency, selected.rail, payer_ref, description, "dispatching", None, idempotency_key, ts, ts),
            )
            conn.execute(
                """INSERT INTO route_decisions(payment_id,requested_rail,selected_rail,score,cost_bps,latency_ms,success_probability,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (payment_id, requested_rail, selected.rail, selected.score, selected.cost_bps, selected.latency_ms, selected.success_probability, ts),
            )
            updated = conn.execute(
                """UPDATE payment_idempotency
                   SET status='committed',payment_id=?,updated_at=?
                   WHERE idempotency_key=? AND request_hash=? AND status='reserved'""",
                (payment_id, ts, idempotency_key, request_hash),
            )
            if updated.rowcount != 1:
                raise PaymentError("payment idempotency reservation was lost before production dispatch")
            append_audit(
                "payment.production_dispatch_committed",
                payment_id,
                {
                    "merchant_id": merchant_id,
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "requested_rail": requested_rail,
                    "selected_rail": selected.rail,
                    "risk_score": risk_score,
                    "risk_decision_id": risk_decision_id,
                    "idempotency_key": idempotency_key,
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _finish_production_dispatch(payment_id: str, *, external_reference: str, provider_status: str) -> dict:
    ts = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                """UPDATE payment_intents
                   SET status='pending',external_reference=?,updated_at=?
                   WHERE id=? AND status='dispatching'""",
                (external_reference, ts, payment_id),
            )
            if updated.rowcount != 1:
                raise PaymentError("production payment state changed before dispatch result commit")
            append_audit(
                "payment.production_dispatched",
                payment_id,
                {"external_reference": external_reference, "provider_initial_status": provider_status},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    payment = get_payment(payment_id)
    if not payment:
        raise PaymentError("production payment disappeared after dispatch")
    payment["provider_initial_status"] = provider_status
    payment["reconciliation_required"] = False
    return payment


def _mark_production_dispatch_ambiguous(payment_id: str, error_type: str) -> dict:
    ts = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = conn.execute(
                """UPDATE payment_intents
                   SET status='provider_ambiguous',updated_at=?
                   WHERE id=? AND status='dispatching'""",
                (ts, payment_id),
            )
            if updated.rowcount not in {0, 1}:
                raise PaymentError("unexpected production payment state update count")
            append_audit(
                "payment.production_dispatch_ambiguous",
                payment_id,
                {"error_type": error_type, "automatic_retry": False},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    payment = get_payment(payment_id)
    if not payment:
        raise PaymentError("ambiguous production payment disappeared")
    payment["reconciliation_required"] = True
    payment["automatic_retry_allowed"] = False
    return payment


def _decorate_payment(payment: dict, selected, requested_rail: str, risk_score: int) -> dict:
    payment["routing"] = {
        "requested_rail": requested_rail,
        "selected_rail": selected.rail,
        "score": selected.score,
        "cost_bps": selected.cost_bps,
        "latency_ms": selected.latency_ms,
        "success_probability": selected.success_probability,
    }
    payment["risk_score"] = risk_score
    if payment.get("status") in {"dispatching", "provider_ambiguous"}:
        payment["reconciliation_required"] = True
        payment["automatic_retry_allowed"] = False
    return payment


async def create_payment_intent(*, merchant_id: str, destination_account_id: str, amount_minor: int, currency: str, rail: str, payer_ref: str | None, description: str | None, idempotency_key: str, callback_url: str | None = None) -> dict:
    currency = currency.upper()
    requested_rail = rail.lower()
    if requested_rail != "auto" and requested_rail not in RAILS:
        raise PaymentError(f"Unsupported rail: {requested_rail}")
    if amount_minor <= 0:
        raise PaymentError("amount_minor must be positive")
    if amount_minor > settings.max_single_payment_minor:
        raise PaymentError("payment exceeds configured single-payment limit")
    with connect() as conn:
        merchant = conn.execute("SELECT * FROM merchants WHERE id=?", (merchant_id,)).fetchone()
        account = conn.execute("SELECT * FROM accounts WHERE id=?", (destination_account_id,)).fetchone()
        if not merchant or not account:
            raise PaymentError("merchant or destination account not found")
        allowed_merchant_statuses = {"active"} if settings.environment == "production" else {"sandbox", "active"}
        if merchant["status"] not in allowed_merchant_statuses:
            raise PaymentError("merchant is not approved for payment processing")
        if account["owner_type"] != "merchant" or account["owner_id"] != merchant_id:
            raise PaymentError("destination account does not belong to merchant")
        if account["status"] != "active":
            raise PaymentError("destination account is not active")
        if account["currency"] != currency:
            raise PaymentError("currency does not match destination account")

    selected = choose_route(list(RAILS)) if requested_rail == "auto" else score_route(requested_rail)
    policy = evaluate_payment_policy(amount_minor=amount_minor, currency=currency, rail=selected.rail, max_amount_minor=settings.max_single_payment_minor)
    if not policy.allow:
        raise PaymentError(f"policy denied: {policy.reason}")
    risk = evaluate_reference_risk(
        amount_minor=amount_minor,
        payer_ref=payer_ref,
        description=description,
        merchant_id=merchant_id,
        destination_account_id=destination_account_id,
        currency=currency,
        rail=selected.rail,
        idempotency_key=idempotency_key,
    )
    if not risk.allow:
        raise PaymentError(f"risk denied: {risk.reason}")

    request_hash = _payment_request_hash(
        merchant_id=merchant_id,
        destination_account_id=destination_account_id,
        amount_minor=amount_minor,
        currency=currency,
        requested_rail=requested_rail,
        payer_ref=payer_ref,
        description=description,
        callback_url=callback_url,
    )
    idem_state, existing_payment_id = _begin_payment_idempotency(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        merchant_id=merchant_id,
        destination_account_id=destination_account_id,
        amount_minor=amount_minor,
        currency=currency,
        requested_rail=requested_rail,
        payer_ref=payer_ref,
        description=description,
        callback_url=callback_url,
    )
    if idem_state in {"committed", "legacy"}:
        payment = get_payment(existing_payment_id or "")
        if not payment:
            raise PaymentError("idempotency record references a missing payment")
        return _decorate_payment(payment, selected, requested_rail, risk.score)

    payment_id = f"pay_{uuid.uuid4().hex}"
    ts = now_iso()

    if settings.is_production:
        try:
            _persist_production_dispatch(
                payment_id=payment_id,
                merchant_id=merchant_id,
                destination_account_id=destination_account_id,
                amount_minor=amount_minor,
                currency=currency,
                selected=selected,
                requested_rail=requested_rail,
                payer_ref=payer_ref,
                description=description,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                risk_score=risk.score,
                risk_decision_id=risk.decision_id,
                ts=ts,
            )
        except Exception:
            try:
                _release_payment_idempotency(idempotency_key, request_hash)
            except Exception:
                pass
            raise

        try:
            result = await RAILS[selected.rail].create_payment(RailRequest(
                payment_id=payment_id,
                amount_minor=amount_minor,
                currency=currency,
                payer_ref=payer_ref,
                description=description,
                callback_url=callback_url,
            ))
        except Exception as exc:
            payment = _mark_production_dispatch_ambiguous(payment_id, type(exc).__name__)
            return _decorate_payment(payment, selected, requested_rail, risk.score)

        payment = _finish_production_dispatch(
            payment_id,
            external_reference=result.external_reference,
            provider_status=result.status,
        )
        return _decorate_payment(payment, selected, requested_rail, risk.score)

    try:
        result = await RAILS[selected.rail].create_payment(RailRequest(
            payment_id=payment_id,
            amount_minor=amount_minor,
            currency=currency,
            payer_ref=payer_ref,
            description=description,
            callback_url=callback_url,
        ))
    except Exception:
        _release_payment_idempotency(idempotency_key, request_hash)
        raise

    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """INSERT INTO payment_intents
                (id,merchant_id,destination_account_id,amount_minor,currency,rail,payer_ref,description,status,external_reference,idempotency_key,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payment_id, merchant_id, destination_account_id, amount_minor, currency, selected.rail, payer_ref, description, result.status, result.external_reference, idempotency_key, ts, ts),
            )
            conn.execute(
                """INSERT INTO route_decisions(payment_id,requested_rail,selected_rail,score,cost_bps,latency_ms,success_probability,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (payment_id, requested_rail, selected.rail, selected.score, selected.cost_bps, selected.latency_ms, selected.success_probability, ts),
            )
            updated = conn.execute(
                """UPDATE payment_idempotency
                   SET status='committed',payment_id=?,updated_at=?
                   WHERE idempotency_key=? AND request_hash=? AND status='reserved'""",
                (payment_id, ts, idempotency_key, request_hash),
            )
            if updated.rowcount != 1:
                raise PaymentError("payment idempotency reservation was lost before commit")
            append_audit("payment.created", payment_id, {
                "merchant_id": merchant_id,
                "amount_minor": amount_minor,
                "currency": currency,
                "requested_rail": requested_rail,
                "selected_rail": selected.rail,
                "risk_score": risk.score,
                "external_reference": result.external_reference,
            }, conn=conn)
            append_audit(
                "payment.idempotency_committed",
                idempotency_key,
                {"payment_id": payment_id, "request_hash": request_hash},
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    payment = get_payment(payment_id)
    if not payment:
        raise PaymentError("payment disappeared after creation")
    return _decorate_payment(payment, selected, requested_rail, risk.score)


async def create_agent_payment(*, mandate_id: str, merchant_id: str, destination_account_id: str, amount_minor: int, currency: str, rail: str, description: str | None, idempotency_key: str) -> dict:
    data = get_agent_mandate(mandate_id)
    if not data or data["status"] != "active":
        raise PaymentError("mandate not found or inactive")
    selected_rail = choose_route(data["allowed_rails"]).rail if rail == "auto" else rail
    mandate = AgentMandate(
        mandate_id=data["id"], principal_id=data["principal_id"], agent_id=data["agent_id"],
        max_per_payment_minor=data["max_per_payment_minor"], max_daily_minor=data["max_daily_minor"],
        currency=data["currency"], allowed_rails=tuple(data["allowed_rails"]),
    )
    allowed, reason = authorize_mandate(mandate, amount_minor=amount_minor, currency=currency, rail=selected_rail)
    if not allowed:
        raise PaymentError(f"mandate denied: {reason}")
    reserved_here = _reserve_mandate_spend(
        mandate_id=mandate_id,
        amount_minor=amount_minor,
        currency=currency,
        max_daily_minor=data["max_daily_minor"],
        idempotency_key=idempotency_key,
    )
    try:
        payment = await create_payment_intent(
            merchant_id=merchant_id, destination_account_id=destination_account_id,
            amount_minor=amount_minor, currency=currency, rail=selected_rail,
            payer_ref=data["agent_id"], description=description,
            idempotency_key=idempotency_key,
        )
    except Exception:
        if reserved_here and not _payment_idempotency_reserved(idempotency_key):
            _release_mandate_spend(idempotency_key)
        raise
    _commit_mandate_spend(idempotency_key, payment["id"])
    return payment


def settle_payment(payment_id: str, provider_event_id: str) -> dict:
    _require_sandbox_for_manual_state_change()
    payment = get_payment(payment_id)
    if not payment:
        raise PaymentError("payment not found")
    if payment["status"] == "succeeded":
        return payment
    if payment["status"] in {"failed", "cancelled", "refunded"}:
        raise PaymentError(f"cannot settle payment in status {payment['status']}")
    rail_account = get_or_create_rail_account(payment["rail"], payment["currency"])
    post(
        reference=f"payment:{payment_id}",
        memo=f"Sandbox settlement {payment['rail']} payment {payment_id}",
        postings=[
            (rail_account["id"], -int(payment["amount_minor"])),
            (payment["destination_account_id"], int(payment["amount_minor"])),
        ],
    )
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE payment_intents SET status='succeeded',updated_at=? WHERE id=?", (now_iso(), payment_id))
            append_audit("payment.sandbox_succeeded", payment_id, {"provider_event_id": provider_event_id}, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return get_payment(payment_id)


def fail_payment(payment_id: str, provider_event_id: str) -> dict:
    _require_sandbox_for_manual_state_change()
    payment = get_payment(payment_id)
    if not payment:
        raise PaymentError("payment not found")
    if payment["status"] == "succeeded":
        raise PaymentError("cannot fail a succeeded payment")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE payment_intents SET status='failed',updated_at=? WHERE id=?", (now_iso(), payment_id))
            append_audit("payment.sandbox_failed", payment_id, {"provider_event_id": provider_event_id}, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return get_payment(payment_id)


def register_webhook_event(provider: str, event_id: str, payload: bytes) -> bool:
    digest = hashlib.sha256(payload).hexdigest()
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO webhook_events(event_id,provider,payload_hash,received_at) VALUES (?,?,?,?)",
                (event_id, provider, digest, now_iso()),
            )
            return True
        except Exception as exc:
            if "UNIQUE" in str(exc).upper() or "PRIMARY KEY" in str(exc).upper():
                return False
            raise


def reconcile() -> dict:
    with connect() as conn:
        unbalanced = conn.execute(
            """SELECT j.id, COALESCE(SUM(p.delta_minor),0) AS net
               FROM journal_entries j JOIN ledger_postings p ON p.journal_id=j.id
               GROUP BY j.id HAVING net != 0"""
        ).fetchall()
        dangling = conn.execute(
            "SELECT COUNT(*) AS n FROM payment_intents WHERE status='succeeded' AND id NOT IN (SELECT REPLACE(reference,'payment:','') FROM journal_entries WHERE reference LIKE 'payment:%')"
        ).fetchone()["n"]
        provider_attention = conn.execute(
            """SELECT id,rail,status,external_reference,updated_at
               FROM payment_intents
               WHERE status IN ('dispatching','provider_ambiguous')
               ORDER BY updated_at"""
        ).fetchall()
    return {
        "balanced": len(unbalanced) == 0,
        "unbalanced_journals": [dict(r) for r in unbalanced],
        "succeeded_without_journal": int(dangling),
        "provider_attention_required": len(provider_attention),
        "provider_attention": [dict(r) for r in provider_attention],
    }
