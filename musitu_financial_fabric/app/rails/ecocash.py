from __future__ import annotations

import uuid

import httpx

from ..config import settings
from .base import PaymentRail, RailRequest, RailResult


class EcoCashRail(PaymentRail):
    name = "ecocash"

    async def create_payment(self, request: RailRequest) -> RailResult:
        # Sandbox-safe default. No undocumented EcoCash endpoint is invented here.
        # Production activation requires exact endpoint paths/field names from the authenticated developer portal.
        if settings.environment != "production":
            return RailResult(
                external_reference=f"ecocash_sandbox_{uuid.uuid4().hex}",
                status="pending",
                raw={"mode": "sandbox-simulated", "payment_id": request.payment_id},
            )

        if not settings.live_funds_enabled:
            raise RuntimeError("Production live-funds gate is disabled")
        required = [
            settings.ecocash_api_base,
            settings.ecocash_oauth_path,
            settings.ecocash_payment_path,
            settings.ecocash_client_id,
            settings.ecocash_client_secret,
        ]
        if not all(required):
            raise RuntimeError("EcoCash production configuration incomplete")

        async with httpx.AsyncClient(base_url=settings.ecocash_api_base, timeout=20) as client:
            token_response = await client.post(
                settings.ecocash_oauth_path,
                data={"grant_type": "client_credentials"},
                auth=(settings.ecocash_client_id, settings.ecocash_client_secret),
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]
            payload = {
                "reference": request.payment_id,
                "amount_minor": request.amount_minor,
                "currency": request.currency,
                "payer_ref": request.payer_ref,
                "description": request.description,
                "callback_url": request.callback_url,
            }
            response = await client.post(
                settings.ecocash_payment_path,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            external_ref = str(data.get("reference") or data.get("id") or request.payment_id)
            status = str(data.get("status") or "pending").lower()
            return RailResult(external_reference=external_ref, status=status, raw=data)
