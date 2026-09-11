from __future__ import annotations

import httpx
from fastapi import Request
from starlette.responses import JSONResponse

from .config import settings
from .security import verify_hmac
from .webhook import WebhookReplayConflict, begin_webhook_delivery, finish_webhook_delivery


_PUBLIC_PRODUCTION_PATHS = {"/health", "/ready"}
_ECOCASH_WEBHOOK_PATH = "/v1/webhooks/ecocash"


async def _introspect(token: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            settings.auth_introspection_url,
            data={"token": token},
            auth=(settings.auth_client_id, settings.auth_client_secret),
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("active") is not True:
        raise ValueError("inactive token")
    required_scope = settings.auth_required_scope.strip()
    scopes = set(str(payload.get("scope", "")).split())
    if required_scope and required_scope not in scopes:
        raise ValueError("required scope missing")
    if not str(payload.get("sub") or payload.get("client_id") or "").strip():
        raise ValueError("token subject missing")
    return payload


async def _authorize(principal: dict, request: Request) -> dict:
    if not settings.authz_gate_url:
        raise ValueError("authorization gate unconfigured")
    subject = str(principal.get("sub") or principal.get("client_id")).strip()
    headers = {"Content-Type": "application/json"}
    if settings.authz_gate_token:
        headers["Authorization"] = f"Bearer {settings.authz_gate_token}"
    payload = {
        "subject": subject,
        "method": request.method.upper(),
        "path": request.url.path,
        "required_engines": ["openfga", "opa"],
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(settings.authz_gate_url, json=payload, headers=headers)
        response.raise_for_status()
        decision = response.json()
    if not isinstance(decision, dict) or decision.get("allow") is not True:
        raise PermissionError("authorization denied")
    engines = {str(value).lower() for value in decision.get("engines", []) if isinstance(value, str)}
    if not {"openfga", "opa"}.issubset(engines):
        raise PermissionError("authorization evidence incomplete")
    if not str(decision.get("decision_id") or "").strip():
        raise PermissionError("authorization decision id missing")
    return decision


async def _production_ecocash_webhook(request: Request, call_next):
    body = await request.body()
    signature = request.headers.get("X-EcoCash-Signature", "")
    if not verify_hmac(body, signature, settings.webhook_secret):
        return await call_next(request)

    try:
        delivery_state = begin_webhook_delivery("ecocash", body)
    except WebhookReplayConflict:
        return JSONResponse({"detail": "webhook replay conflict"}, status_code=409)

    if delivery_state == "inflight":
        return JSONResponse(
            {"detail": "webhook delivery is already processing"},
            status_code=503,
            headers={"Retry-After": "5"},
        )

    response = await call_next(request)
    if delivery_state == "process":
        try:
            finish_webhook_delivery("ecocash", body, response.status_code)
        except Exception:
            return JSONResponse(
                {"detail": "webhook delivery state could not be persisted"},
                status_code=503,
                headers={"Retry-After": "5"},
            )
    return response


async def production_auth_middleware(request: Request, call_next):
    if not settings.is_production:
        return await call_next(request)
    if request.url.path == _ECOCASH_WEBHOOK_PATH:
        return await _production_ecocash_webhook(request, call_next)
    if request.url.path in _PUBLIC_PRODUCTION_PATHS:
        return await call_next(request)

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return JSONResponse({"detail": "production bearer token required"}, status_code=401)
    try:
        principal = await _introspect(token.strip())
    except Exception:
        return JSONResponse({"detail": "production authentication failed"}, status_code=401)
    try:
        decision = await _authorize(principal, request)
    except PermissionError:
        return JSONResponse({"detail": "production authorization denied"}, status_code=403)
    except Exception:
        return JSONResponse({"detail": "production authorization unavailable"}, status_code=503)
    request.state.principal = principal
    request.state.authorization_decision = decision
    return await call_next(request)
