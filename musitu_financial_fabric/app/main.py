from __future__ import annotations

import json
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .audit import verify_audit_chain
from .auth import authorize_resource, production_auth_middleware
from .component_registry import component_manifest, probe_components
from .config import settings
from .db import init_db
from .ledger import balance, get_account
from .merchant_lifecycle import MerchantLifecycleError, review_merchant
from .production import ProductionGateError, enforce_safe_startup, production_readiness
from .protocols.adapters import gsma_transaction, iso20022_pacs008, mpp_challenge, open_payments_incoming, stripe_payment_intent, x402_challenge
from .reconciliation import reconcile_monetary_truth
from .security import verify_hmac
from .service import PaymentError, create_agent_mandate, create_agent_payment, create_identity, create_merchant, create_payment_intent, get_agent_mandate, get_payment, reconcile, register_webhook_event, settle_payment
from .settlement import ProviderSettlementError, provider_fail, provider_succeed
from .sovereign import SovereignError, calculate_net_positions, close_settlement_cycle, create_certification_case, create_qr_record, create_request_to_pay, create_scheme_exception, create_scheme_participant, decide_certification, decide_scheme_exception, open_settlement_cycle, record_certification_check, record_clearing_obligation, record_exception_evidence, register_payment_alias, register_qr_scheme_profile, resolve_payment_alias, resolve_qr_record, respond_request_to_pay, set_participant_status, sovereign_capabilities


@asynccontextmanager
async def lifespan(_: FastAPI):
    enforce_safe_startup()
    init_db()
    yield


app = FastAPI(title="MUSITU Financial Fabric", version="0.3.0", lifespan=lifespan)
app.middleware("http")(production_auth_middleware)


@app.exception_handler(ProductionGateError)
async def production_gate_error(_: Request, exc: ProductionGateError):
    return JSONResponse({"detail": str(exc), "production_gate": "closed"}, status_code=503)


class MerchantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class SovereignParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    participant_type: str = Field(min_length=1, max_length=32)
    scheme_code: str = Field(min_length=1, max_length=64)


class SovereignParticipantStatus(BaseModel):
    status: str = Field(min_length=5, max_length=16)
    evidence_ref: str = Field(min_length=1, max_length=512)


class SovereignAliasCreate(BaseModel):
    participant_id: str = Field(min_length=1, max_length=96)
    alias: str = Field(min_length=1, max_length=256)
    account_ref: str = Field(min_length=1, max_length=256)
    alias_type: str = Field(min_length=1, max_length=32)


class SovereignCertificationCreate(BaseModel):
    participant_id: str = Field(min_length=1, max_length=96)
    scheme_profile: str = Field(min_length=1, max_length=96)
    evidence_ref: str = Field(min_length=1, max_length=512)
    required_checks: list[str]


class SovereignCertificationCheck(BaseModel):
    check_key: str = Field(min_length=1, max_length=96)
    result: str = Field(min_length=6, max_length=6)
    evidence_ref: str = Field(min_length=1, max_length=512)


class SovereignCertificationDecision(BaseModel):
    decision: str = Field(min_length=8, max_length=8)


class SovereignExceptionCreate(BaseModel):
    transaction_ref: str = Field(min_length=1, max_length=256)
    kind: str = Field(min_length=1, max_length=32)
    claimant_participant_id: str = Field(min_length=1, max_length=96)
    reason: str = Field(min_length=1, max_length=512)


class SovereignExceptionEvidence(BaseModel):
    evidence_ref: str = Field(min_length=1, max_length=512)


class SovereignExceptionDecision(BaseModel):
    decision: str = Field(min_length=8, max_length=9)


class SovereignSettlementCycleCreate(BaseModel):
    profile_key: str = Field(min_length=1, max_length=96)
    cycle_ref: str = Field(min_length=1, max_length=256)
    currency: str = Field(min_length=3, max_length=3)


class SovereignClearingObligationCreate(BaseModel):
    debtor_participant_id: str = Field(min_length=1, max_length=96)
    creditor_participant_id: str = Field(min_length=1, max_length=96)
    amount_minor: int = Field(gt=0)
    external_ref: str = Field(min_length=1, max_length=256)


class SovereignSettlementCycleClose(BaseModel):
    evidence_ref: str = Field(min_length=1, max_length=512)


class SovereignQrSchemeProfileCreate(BaseModel):
    participant_id: str = Field(min_length=1, max_length=96)
    profile_key: str = Field(min_length=1, max_length=64)
    mai_id: str = Field(min_length=2, max_length=2)
    allocation_ref: str = Field(min_length=1, max_length=512)


class SovereignQrCreate(BaseModel):
    participant_id: str = Field(min_length=1, max_length=96)
    merchant_ref: str = Field(min_length=1, max_length=256)
    alias: str = Field(min_length=1, max_length=256)
    currency: str = Field(min_length=3, max_length=3)
    amount_minor: int | None = None
    expires_at: str | None = None
    profile_key: str = Field(default="generic", min_length=1, max_length=64)
    scheme_profile_id: str | None = Field(default=None, max_length=96)
    channel: str = Field(default="pos", min_length=1, max_length=32)


class SovereignRequestToPayCreate(BaseModel):
    payee_alias: str = Field(min_length=1, max_length=256)
    payer_alias: str = Field(min_length=1, max_length=256)
    amount_minor: int
    currency: str = Field(min_length=3, max_length=3)
    reference: str = Field(min_length=1, max_length=512)


class SovereignRequestToPayResponse(BaseModel):
    decision: str = Field(min_length=7, max_length=9)
    actor_alias: str = Field(min_length=1, max_length=256)


class MerchantReview(BaseModel):
    status: str = Field(min_length=5, max_length=16)
    evidence_ref: str = Field(min_length=1, max_length=512)


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


def _audit_readiness() -> dict:
    try:
        valid, count, broken_at = verify_audit_chain()
        return {"valid": valid, "events": count, "broken_at": broken_at}
    except Exception as exc:
        return {"valid": False, "events": None, "broken_at": None, "error": type(exc).__name__}


def _metadata_reconciliation_readiness() -> dict:
    try:
        result = reconcile()
        dangling = int(result.get("succeeded_without_journal", 0))
        consistent = bool(result.get("balanced", False) and dangling == 0)
        return {**result, "consistent": consistent}
    except Exception as exc:
        return {
            "balanced": False,
            "consistent": False,
            "succeeded_without_journal": None,
            "provider_attention_required": None,
            "error": type(exc).__name__,
        }


async def _readiness_snapshot() -> dict:
    components = await probe_components()
    audit = _audit_readiness()
    metadata_reconciliation = _metadata_reconciliation_readiness()
    monetary_truth = reconcile_monetary_truth()
    production = production_readiness() if settings.is_production else {"ready_for_live_funds": False, "checks": []}
    service_ready = bool(
        components["all_required_runtime_healthy"]
        and audit["valid"]
        and metadata_reconciliation["consistent"]
        and monetary_truth["consistent"]
    )
    live_funds_ready = bool(
        settings.is_production
        and settings.live_funds_enabled
        and production["ready_for_live_funds"]
        and service_ready
    )
    return {
        **components,
        "audit": audit,
        "metadata_reconciliation": metadata_reconciliation,
        "monetary_truth": monetary_truth,
        "service_ready": service_ready,
        "sandbox_api_operational": not settings.is_production,
        "production": production,
        "production_funds_gate": live_funds_ready,
    }


async def _require_resource_authorization(request: Request, resource: dict) -> dict:
    try:
        return await authorize_resource(request, resource)
    except PermissionError as exc:
        raise HTTPException(403, "production resource authorization denied") from exc
    except Exception as exc:
        raise HTTPException(503, "production resource authorization unavailable") from exc


@app.get("/health")
def health():
    if settings.is_production:
        return {"status": "ok"}
    return {
        "status": "ok",
        "environment": settings.environment,
        "production_mode": settings.production_mode,
        "live_funds_enabled": settings.live_funds_enabled,
        "fabric_version": "0.3.0",
    }


@app.get("/ready")
async def ready():
    snapshot = await _readiness_snapshot()
    if settings.is_production:
        public = {"status": "ready" if snapshot["service_ready"] else "not_ready"}
        if not snapshot["service_ready"]:
            return JSONResponse(public, status_code=503)
        return public
    if not snapshot["service_ready"]:
        return JSONResponse(snapshot, status_code=503)
    return snapshot


@app.get("/v1/fabric/components")
def fabric_components():
    return {"required": True, "components": component_manifest()}


@app.get("/v1/fabric/readiness")
async def fabric_readiness():
    return await _readiness_snapshot()


@app.post("/v1/identities")
async def identity_create(payload: IdentityCreate, request: Request):
    await _require_resource_authorization(request, {"type": "identity", "action": "create", "kind": payload.kind})
    try:
        return create_identity(payload.kind, payload.display_name)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/agent-mandates")
async def mandate_create(payload: MandateCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "agent_mandate",
        "action": "create",
        "principal_id": payload.principal_id,
        "agent_id": payload.agent_id,
        "currency": payload.currency.upper(),
        "allowed_rails": sorted({rail.lower() for rail in payload.allowed_rails}),
        "max_per_payment_minor": payload.max_per_payment_minor,
        "max_daily_minor": payload.max_daily_minor,
    })
    try:
        return create_agent_mandate(**payload.model_dump())
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/agent-mandates/{mandate_id}")
async def mandate_get(mandate_id: str, request: Request):
    await _require_resource_authorization(request, {"type": "agent_mandate", "id": mandate_id, "action": "read"})
    data = get_agent_mandate(mandate_id)
    if not data:
        raise HTTPException(404, "mandate not found")
    return data


@app.get("/v1/sovereign/capabilities")
async def sovereign_capabilities_get(request: Request):
    await _require_resource_authorization(request, {"type": "sovereign_capabilities", "action": "read"})
    return {"phase": "reference", "capabilities": sovereign_capabilities()}


@app.post("/v1/sovereign/exceptions")
async def sovereign_exception_create(
    payload: SovereignExceptionCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    await _require_resource_authorization(request, {
        "type": "sovereign_scheme_exception",
        "action": "create",
        "transaction_ref": payload.transaction_ref,
        "kind": payload.kind.lower(),
        "claimant_participant_id": payload.claimant_participant_id,
    })
    try:
        return create_scheme_exception(
            payload.transaction_ref,
            payload.kind,
            payload.claimant_participant_id,
            payload.reason,
            idempotency_key,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/exceptions/{exception_id}/evidence")
async def sovereign_exception_evidence(
    exception_id: str,
    payload: SovereignExceptionEvidence,
    request: Request,
):
    await _require_resource_authorization(request, {
        "type": "sovereign_scheme_exception",
        "id": exception_id,
        "action": "record_evidence",
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return record_exception_evidence(exception_id, payload.evidence_ref, actor)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/exceptions/{exception_id}/decision")
async def sovereign_exception_decision(
    exception_id: str,
    payload: SovereignExceptionDecision,
    request: Request,
):
    resource_decision = await _require_resource_authorization(request, {
        "type": "sovereign_scheme_exception",
        "id": exception_id,
        "action": "decide",
        "decision": payload.decision.lower(),
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    decision_id = str(resource_decision.get("decision_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return decide_scheme_exception(exception_id, payload.decision, actor, decision_id)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/settlement-cycles")
async def sovereign_settlement_cycle_create(payload: SovereignSettlementCycleCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_settlement_cycle",
        "action": "create",
        "profile_key": payload.profile_key.lower(),
        "cycle_ref": payload.cycle_ref,
        "currency": payload.currency.upper(),
    })
    try:
        return open_settlement_cycle(payload.profile_key, payload.cycle_ref, payload.currency)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/settlement-cycles/{cycle_id}/obligations")
async def sovereign_clearing_obligation_create(
    cycle_id: str,
    payload: SovereignClearingObligationCreate,
    request: Request,
):
    await _require_resource_authorization(request, {
        "type": "sovereign_clearing_obligation",
        "action": "create",
        "cycle_id": cycle_id,
        "debtor_participant_id": payload.debtor_participant_id,
        "creditor_participant_id": payload.creditor_participant_id,
        "amount_minor": payload.amount_minor,
        "external_ref": payload.external_ref,
    })
    try:
        return record_clearing_obligation(
            cycle_id,
            payload.debtor_participant_id,
            payload.creditor_participant_id,
            payload.amount_minor,
            payload.external_ref,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/sovereign/settlement-cycles/{cycle_id}/positions")
async def sovereign_settlement_cycle_positions(cycle_id: str, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_settlement_cycle",
        "id": cycle_id,
        "action": "read_positions",
    })
    try:
        return calculate_net_positions(cycle_id)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/settlement-cycles/{cycle_id}/close")
async def sovereign_settlement_cycle_close(
    cycle_id: str,
    payload: SovereignSettlementCycleClose,
    request: Request,
):
    resource_decision = await _require_resource_authorization(request, {
        "type": "sovereign_settlement_cycle",
        "id": cycle_id,
        "action": "close",
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    decision_id = str(resource_decision.get("decision_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return close_settlement_cycle(
            cycle_id,
            payload.evidence_ref,
            actor,
            decision_id,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/certifications")
async def sovereign_certification_create(payload: SovereignCertificationCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_certification",
        "action": "create",
        "participant_id": payload.participant_id,
        "scheme_profile": payload.scheme_profile.lower(),
        "required_checks": sorted({item.strip().lower() for item in payload.required_checks if item.strip()}),
    })
    try:
        return create_certification_case(
            payload.participant_id,
            payload.scheme_profile,
            payload.evidence_ref,
            payload.required_checks,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/certifications/{case_id}/checks")
async def sovereign_certification_check(case_id: str, payload: SovereignCertificationCheck, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_certification",
        "id": case_id,
        "action": "record_check",
        "check_key": payload.check_key.lower(),
        "result": payload.result.lower(),
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return record_certification_check(
            case_id,
            payload.check_key,
            payload.result,
            payload.evidence_ref,
            actor,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/certifications/{case_id}/decision")
async def sovereign_certification_decision(case_id: str, payload: SovereignCertificationDecision, request: Request):
    resource_decision = await _require_resource_authorization(request, {
        "type": "sovereign_certification",
        "id": case_id,
        "action": "decide",
        "decision": payload.decision.lower(),
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    decision_id = str(resource_decision.get("decision_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return decide_certification(case_id, payload.decision, actor, decision_id)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/participants")
async def sovereign_participant_create(payload: SovereignParticipantCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_participant",
        "action": "create",
        "participant_type": payload.participant_type.lower(),
        "scheme_code": payload.scheme_code,
    })
    try:
        return create_scheme_participant(payload.name, payload.participant_type, payload.scheme_code)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/participants/{participant_id}/status")
async def sovereign_participant_status(participant_id: str, payload: SovereignParticipantStatus, request: Request):
    resource_decision = await _require_resource_authorization(request, {
        "type": "sovereign_participant",
        "id": participant_id,
        "action": "status_change",
        "target_status": payload.status.lower(),
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    decision_id = str(resource_decision.get("decision_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return set_participant_status(
            participant_id,
            payload.status,
            evidence_ref=payload.evidence_ref,
            actor=actor,
            authorization_decision_id=decision_id,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/aliases")
async def sovereign_alias_create(payload: SovereignAliasCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_alias",
        "action": "create",
        "participant_id": payload.participant_id,
        "alias_type": payload.alias_type.lower(),
    })
    try:
        return register_payment_alias(payload.participant_id, payload.alias, payload.account_ref, payload.alias_type)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/sovereign/aliases/{alias}")
async def sovereign_alias_get(alias: str, request: Request):
    await _require_resource_authorization(request, {"type": "sovereign_alias", "action": "read", "alias": alias.lower()})
    resolved = resolve_payment_alias(alias)
    if not resolved:
        raise HTTPException(404, "payment alias not found")
    return resolved


@app.post("/v1/sovereign/qr-scheme-profiles")
async def sovereign_qr_scheme_profile_create(payload: SovereignQrSchemeProfileCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_qr_scheme_profile",
        "action": "create",
        "participant_id": payload.participant_id,
        "profile_key": payload.profile_key.lower(),
        "mai_id": payload.mai_id,
    })
    try:
        return register_qr_scheme_profile(
            payload.participant_id,
            payload.profile_key,
            payload.mai_id,
            payload.allocation_ref,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/qr")
async def sovereign_qr_create(payload: SovereignQrCreate, request: Request):
    await _require_resource_authorization(request, {
        "type": "sovereign_qr",
        "action": "create",
        "participant_id": payload.participant_id,
        "currency": payload.currency.upper(),
        "amount_minor": payload.amount_minor,
        "profile_key": payload.profile_key.lower(),
        "channel": payload.channel.lower(),
    })
    try:
        return create_qr_record(
            payload.participant_id,
            payload.merchant_ref,
            payload.alias,
            payload.currency,
            amount_minor=payload.amount_minor,
            expires_at=payload.expires_at,
            profile_key=payload.profile_key,
            scheme_profile_id=payload.scheme_profile_id,
            channel=payload.channel,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/sovereign/qr/{qr_id}")
async def sovereign_qr_get(qr_id: str, nonce: str, request: Request):
    await _require_resource_authorization(request, {"type": "sovereign_qr", "id": qr_id, "action": "read"})
    record = resolve_qr_record(qr_id, nonce)
    if not record:
        raise HTTPException(404, "QR record not found")
    return record


@app.post("/v1/sovereign/requests-to-pay")
async def sovereign_request_to_pay_create(
    payload: SovereignRequestToPayCreate,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    await _require_resource_authorization(request, {
        "type": "sovereign_request_to_pay",
        "action": "create",
        "payee_alias": payload.payee_alias.lower(),
        "payer_alias": payload.payer_alias.lower(),
        "amount_minor": payload.amount_minor,
        "currency": payload.currency.upper(),
    })
    try:
        return create_request_to_pay(
            payload.payee_alias,
            payload.payer_alias,
            payload.amount_minor,
            payload.currency,
            payload.reference,
            idempotency_key,
        )
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/sovereign/requests-to-pay/{request_id}/response")
async def sovereign_request_to_pay_response(
    request_id: str,
    payload: SovereignRequestToPayResponse,
    request: Request,
):
    await _require_resource_authorization(request, {
        "type": "sovereign_request_to_pay",
        "id": request_id,
        "action": "respond",
        "decision": payload.decision.lower(),
        "actor_alias": payload.actor_alias.lower(),
    })
    try:
        return respond_request_to_pay(request_id, payload.decision, payload.actor_alias)
    except SovereignError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/merchants")
async def merchant_create(payload: MerchantCreate, request: Request):
    await _require_resource_authorization(request, {"type": "merchant", "action": "create", "currency": payload.currency.upper()})
    return create_merchant(payload.name, payload.currency)


@app.post("/v1/merchants/{merchant_id}/review")
async def merchant_review(merchant_id: str, payload: MerchantReview, request: Request):
    resource_decision = await _require_resource_authorization(request, {
        "type": "merchant",
        "id": merchant_id,
        "action": "review",
        "target_status": payload.status.lower(),
    })
    principal = getattr(request.state, "principal", {}) or {}
    actor = str(principal.get("sub") or principal.get("client_id") or ("sandbox" if not settings.is_production else "")).strip()
    decision_id = str(resource_decision.get("decision_id") or ("sandbox" if not settings.is_production else "")).strip()
    try:
        return review_merchant(
            merchant_id=merchant_id,
            target_status=payload.status,
            evidence_ref=payload.evidence_ref,
            actor=actor,
            authorization_decision_id=decision_id,
        )
    except MerchantLifecycleError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/accounts/{account_id}")
async def account_get(account_id: str, request: Request):
    await _require_resource_authorization(request, {"type": "account", "id": account_id, "action": "read"})
    account = get_account(account_id)
    if not account:
        raise HTTPException(404, "account not found")
    account["balance_minor"] = balance(account_id)
    return account


@app.post("/v1/payments/intents")
async def payment_create(payload: PaymentCreate, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
    await _require_resource_authorization(request, {
        "type": "payment_intent",
        "action": "create",
        "merchant_id": payload.merchant_id,
        "destination_account_id": payload.destination_account_id,
        "amount_minor": payload.amount_minor,
        "currency": payload.currency.upper(),
        "rail": payload.rail.lower(),
    })
    try:
        payment = await create_payment_intent(merchant_id=payload.merchant_id, destination_account_id=payload.destination_account_id, amount_minor=payload.amount_minor, currency=payload.currency, rail=payload.rail, payer_ref=payload.payer_ref, description=payload.description, idempotency_key=idempotency_key, callback_url=payload.callback_url)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc
    payment["musitu_payment_uri"] = "musitu://pay?" + urlencode({"payment_id": payment["id"]})
    return payment


@app.post("/v1/agent-payments")
async def agent_payment_create(payload: AgentPaymentCreate, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
    await _require_resource_authorization(request, {
        "type": "agent_payment",
        "action": "create",
        "mandate_id": payload.mandate_id,
        "merchant_id": payload.merchant_id,
        "destination_account_id": payload.destination_account_id,
        "amount_minor": payload.amount_minor,
        "currency": payload.currency.upper(),
        "rail": payload.rail.lower(),
    })
    try:
        return await create_agent_payment(**payload.model_dump(), idempotency_key=idempotency_key)
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/v1/payments/{payment_id}")
async def payment_get(payment_id: str, request: Request):
    await _require_resource_authorization(request, {"type": "payment", "id": payment_id, "action": "read"})
    payment = get_payment(payment_id)
    if not payment:
        raise HTTPException(404, "payment not found")
    return payment


async def _normalized_payment(request: Request, envelope: ProtocolPaymentEnvelope, intent, idempotency_key: str):
    await _require_resource_authorization(request, {
        "type": "payment_intent",
        "action": "create",
        "merchant_id": envelope.merchant_id,
        "destination_account_id": envelope.destination_account_id,
        "amount_minor": int(intent.amount_minor),
        "currency": str(intent.currency).upper(),
        "rail": envelope.rail.lower(),
    })
    try:
        return await create_payment_intent(merchant_id=envelope.merchant_id, destination_account_id=envelope.destination_account_id, amount_minor=intent.amount_minor, currency=intent.currency, rail=envelope.rail, payer_ref=intent.payer_ref, description=intent.description, idempotency_key=idempotency_key)
    except (PaymentError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/compat/stripe/v1/payment_intents")
async def stripe_compat_payment(envelope: ProtocolPaymentEnvelope, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        intent = stripe_payment_intent(envelope.payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid Stripe-compatible payload: {exc}") from exc
    payment = await _normalized_payment(request, envelope, intent, idempotency_key)
    return {"id": payment["id"], "object": "payment_intent", "amount": payment["amount_minor"], "currency": payment["currency"].lower(), "status": "processing" if payment["status"] == "pending" else payment["status"], "musitu_rail": payment["rail"]}


@app.post("/open-payments/incoming-payments")
async def open_payments_create(envelope: ProtocolPaymentEnvelope, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        intent = open_payments_incoming(envelope.payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid Open Payments payload: {exc}") from exc
    payment = await _normalized_payment(request, envelope, intent, idempotency_key)
    return {"id": payment["id"], "incomingAmount": {"value": str(payment["amount_minor"]), "assetCode": payment["currency"], "assetScale": 2}, "completed": payment["status"] == "succeeded"}


@app.post("/gsma/mmapi/transactions")
async def gsma_mmapi_create(envelope: ProtocolPaymentEnvelope, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")):
    try:
        intent = gsma_transaction(envelope.payload)
    except Exception as exc:
        raise HTTPException(400, f"invalid GSMA MMAPI payload: {exc}") from exc
    payment = await _normalized_payment(request, envelope, intent, idempotency_key)
    return {"transactionReference": payment["id"], "transactionStatus": "Pending" if payment["status"] == "pending" else payment["status"].title()}


@app.post("/iso20022/pacs008")
async def iso20022_create(request: Request, merchant_id: str, destination_account_id: str, rail: str = "auto", idempotency_key: str = Header(alias="Idempotency-Key")):
    body = (await request.body()).decode("utf-8")
    try:
        intent = iso20022_pacs008(body)
        envelope = ProtocolPaymentEnvelope(merchant_id=merchant_id, destination_account_id=destination_account_id, payload={}, rail=rail)
        payment = await _normalized_payment(request, envelope, intent, idempotency_key)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"invalid ISO 20022 pacs.008: {exc}") from exc
    return {"TxSts": "ACSP" if payment["status"] == "pending" else "ACCC", "MusituPaymentId": payment["id"]}


@app.get("/mpp/challenge")
def mpp_payment_challenge(amount_minor: int, currency: str, resource: str, response: Response):
    response.status_code = 402
    return mpp_challenge(amount_minor, currency, resource)


@app.get("/x402/challenge")
def x402_payment_challenge(amount_minor: int, currency: str, resource: str, response: Response):
    response.status_code = 402
    return x402_challenge(amount_minor, currency, resource)


@app.post("/v1/sandbox/payments/{payment_id}/succeed")
def sandbox_succeed(payment_id: str):
    if settings.is_production:
        raise HTTPException(404, "not found")
    try:
        return settle_payment(payment_id, provider_event_id="sandbox-manual")
    except PaymentError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/v1/webhooks/ecocash")
async def ecocash_webhook(request: Request, x_ecocash_signature: str = Header(alias="X-EcoCash-Signature")):
    if settings.is_production and not settings.ecocash_contract_confirmed:
        raise HTTPException(503, "EcoCash production webhook contract is not confirmed")
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
            payment = provider_succeed(provider="ecocash", payment_id=payment_id, provider_event_id=event_id)
        elif status in {"failed", "declined", "cancelled", "canceled"}:
            payment = provider_fail(provider="ecocash", payment_id=payment_id, provider_event_id=event_id)
        else:
            payment = get_payment(payment_id)
            if not payment:
                raise ProviderSettlementError("payment not found")
    except (ProviderSettlementError, PaymentError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"accepted": True, "duplicate": False, "payment": payment}


@app.get("/v1/reconciliation")
def reconciliation():
    result = reconcile()
    monetary_truth = reconcile_monetary_truth()
    try:
        dangling = int(result.get("succeeded_without_journal", 0))
    except (TypeError, ValueError):
        dangling = -1
    metadata_balanced = bool(result.get("balanced", False) and dangling == 0)
    result["metadata_balanced"] = metadata_balanced
    result["monetary_truth"] = monetary_truth
    result["balanced"] = bool(metadata_balanced and monetary_truth["consistent"])
    return result


@app.get("/v1/audit/verify")
def audit_verify():
    valid, count, broken_at = verify_audit_chain()
    return {"valid": valid, "events": count, "broken_at": broken_at}