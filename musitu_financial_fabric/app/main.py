from __future__ import annotations

import json
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .audit import verify_audit_chain
from .component_registry import component_manifest, probe_components
from .config import settings
from .db import init_db
from .ledger import balance, get_account
from .protocols.adapters import (
    gsma_transaction,
    iso20022_pacs008,
    mpp_challenge,
    open_payments_incoming,
    stripe_payment_intent,
    x402_challenge,
)
from .security import verify_hmac
from .service import (
    PaymentError,
    create_agent_mandate,
    create_agent_payment,
    create_identity,
    create_merchant,
    create_payment_intent,
    fail_payment,
    get_agent_mandate,
    get_payment,
    reconcile,
    register_webhook_event,
    settle_payment,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="MUSITU Financial Fabric", version="0.2.0", lifespan=lifespan)


class MerchantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class IdentityCreate(BaseModel):
    kind: str
    display_name: str = Field(min_length=1, max_length=160)


class MandateCreate(BaseModel):
    principal_id: str
    agent_id: str
    max_per_payment_minor: int = Field(gt=0)
    max_daily_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    allowed_rails: list[str]


class PaymentCreate(BaseModel):
    merchant_id: str
    destination_account_id: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    rail: str = "auto"
    payer_ref: str | None = None
    description: str | None = Field(default=None, max_length=280)
    callback_url: str | None = None


class AgentPaymentCreate(BaseModel):
    mandate_id: str
    merchant_id: str
    destination_account_id: str
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    rail: str = "auto"
    description: str | None = Field(default=None, max_length=280)


class ProtocolPaymentEnvelope(BaseModel):
    merchant_id: str
    destination_account_id: str
    payload: dict
    rail: str = "auto"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "environment": settings.environment,
        "live_funds_enabled": settings.live_funds_enabled,
        "custody_mode": "disabled" if not settings.live_funds_enabled else "explicitly-enabled",
        "fabric_version": "0.2.0",
    }


@app.get("/v1/fabric/components")
def fabric_components():
    return {"required": True, "components": component_manifest()}


@app.get("/v1/fabric/readiness")
async def fabric_readiness():
    result = await probe_components()
    result["production_funds_gate"] = bool(settings.environment == "production" and settings.live_funds_enabled)
    result["sandbox_api_operational"] = True
    return result


@app.post("/v1/identities")
def identity_create(payload: IdentityCreate):
    try:
        return create_identity(payload.kind, payload.display_name)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/agent-mandates")
def mandate_create(payload: MandateCreate):
    try:
        return create_agent_mandate(**payload.model_dump())
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/agent-mandates/{mandate_id}")
def mandate_get(mandate_id: str):
    data = get_agent_mandate(mandate_id)
    if not data:
        raise HTTPException(404, "mandate not found")
    return data


@app.post("/v1/merchants")
def merchant_create(payload: MerchantCreate):
    return create_merchant(payload.name, payload.currency)


@app.get("/v1/accounts/{account_id}")
def account_get(account_id: str):
    account = get_account(account_id)
    if not account:
        raise HTTPException(404, "account not found")
    account["balance_minor"] = balance(account_id)
    return account


@app.post("/v1/payments/intents")
async def payment_create(payload: PaymentCreate, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        payment = await create_payment_intent(
            merchant_id=payload.merchant_id,
            destination_account_id=payload.destination_account_id,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            rail=payload.rail,
            payer_ref=payload.payer_ref,
            description=payload.description,
            idempotency_key=idempotency_key,
            callback_url=payload.callback_url,
        )
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc
    payment["musitu_payment_uri"] = "musitu://pay?" + urlencode({"payment_id": payment["id"]})
    return payment


@app.post("/v1/agent-payments")
async def agent_payment_create(payload: AgentPaymentCreate, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        return await create_agent_payment(**payload.model_dump(), idempotency_key=idempotency_key)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/payments/{payment_id}")
def payment_get(payment_id: str):
    payment = get_payment(payment_id)
    if not payment:
        raise HTTPException(404, "payment not found")
    return payment


async def _normalized_payment(envelope: ProtocolPaymentEnvelope, intent, idempotency_key: str):
    try:
        return await create_payment_intent(
            merchant_id=envelope.merchant_id,
            destination_account_id=envelope.destination_account_id,
            amount_minor=intent.amount_minor,
            currency=intent.currency,
            rail=envelope.rail,
            payer_ref=intent.payer_ref,
            description=intent.description,
            idempotency_key=idempotency_key,
        )
    except (PaymentError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/compat/stripe/v1/payment_intents")
async def stripe_compat_payment(envelope: ProtocolPaymentEnvelope, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        intent = stripe_payment_intent(envelope.payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid Stripe-compatible payload: {exc}") from exc
    payment = await _normalized_payment(envelope, intent, idempotency_key)
    return {
        "id": payment["id"], "object": "payment_intent", "amount": payment["amount_minor"],
        "currency": payment["currency"].lower(), "status": "processing" if payment["status"] == "pending" else payment["status"],
        "musitu_rail": payment["rail"],
    }


@app.post("/open-payments/incoming-payments")
async def open_payments_create(envelope: ProtocolPaymentEnvelope, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        intent = open_payments_incoming(envelope.payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid Open Payments payload: {exc}") from exc
    payment = await _normalized_payment(envelope, intent, idempotency_key)
    return {"id": payment["id"], "incomingAmount": {"value": str(payment["amount_minor"]), "assetCode": payment["currency"], "assetScale": 2}, "completed": payment["status"] == "succeeded"}


@app.post("/gsma/mmapi/transactions")
async def gsma_mmapi_create(envelope: ProtocolPaymentEnvelope, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        intent = gsma_transaction(envelope.payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid GSMA MMAPI payload: {exc}") from exc
    payment = await _normalized_payment(envelope, intent, idempotency_key)
    return {"transactionReference": payment["id"], "transactionStatus": "Pending" if payment["status"] == "pending" else payment["status"].title()}


@app.post("/iso20022/pacs008")
async def iso20022_create(request: Request, merchant_id: str, destination_account_id: str, rail: str = "auto", idempotency_key: str = Header(alias="Idempotency-Key")):
    body = (await request.body()).decode("utf-8")
    try:
        intent = iso20022_pacs008(body)
        envelope = ProtocolPaymentEnvelope(merchant_id=merchant_id, destination_account_id=destination_account_id, payload={}, rail=rail)
        payment = await _normalized_payment(envelope, intent, idempotency_key)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"invalid ISO 20022 pacs.008: {exc}") from exc
    return {"TxSts": "ACSP" if payment["status"] == "pending" else "ACCC", "MusituPaymentId": payment["id"]}


@app.get("/mpp/challenge")
def mpp_payment_challenge(amount_minor: int, currency: str, resource: str, response: Response):
    challenge = mpp_challenge(amount_minor, currency, resource)
    response.status_code = 402
    return challenge


@app.get("/x402/challenge")
def x402_payment_challenge(amount_minor: int, currency: str, resource: str, response: Response):
    challenge = x402_challenge(amount_minor, currency, resource)
    response.status_code = 402
    return challenge


@app.post("/v1/sandbox/payments/{payment_id}/succeed")
def sandbox_succeed(payment_id: str):
    if settings.environment == "production":
        raise HTTPException(404, "not found")
    try:
        return settle_payment(payment_id, provider_event_id="sandbox-manual")
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/webhooks/ecocash")
async def ecocash_webhook(request: Request, x_ecocash_signature: str = Header(alias="X-EcoCash-Signature")):
    body = await request.body()
    if not verify_hmac(body, x_ecocash_signature, settings.webhook_secret):
        raise HTTPException(401, "invalid webhook signature")
    try:
        payload = json.loads(body)
        event_id = str(payload["event_id"])
        payment_id = str(payload["payment_id"])
        status = str(payload["status"]).lower()
    except Exception as exc:
        raise HTTPException(400, "invalid webhook payload") from exc
    payment = get_payment(payment_id)
    if not payment:
        raise HTTPException(400, "payment not found")
    if payment["rail"] != "ecocash":
        raise HTTPException(400, "payment rail does not match EcoCash webhook")
    if not register_webhook_event("ecocash", event_id, body):
        return {"accepted": True, "duplicate": True}
    try:
        if status in {"succeeded", "success", "paid", "completed"}:
            payment = settle_payment(payment_id, event_id)
        elif status in {"failed", "declined", "cancelled", "canceled"}:
            payment = fail_payment(payment_id, event_id)
        else:
            payment = get_payment(payment_id)
            if not payment:
                raise PaymentError("payment not found")
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"accepted": True, "duplicate": False, "payment": payment}


@app.get("/v1/reconciliation")
def reconciliation():
    return reconcile()


@app.get("/v1/audit/verify")
def audit_verify():
    valid, count, broken_at = verify_audit_chain()
    return {"valid": valid, "events": count, "broken_at": broken_at}
