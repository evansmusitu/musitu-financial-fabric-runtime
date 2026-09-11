from __future__ import annotations

import uuid

import httpx

from ..config import settings
from ..production import assert_live_funds_allowed
from .base import PaymentRail, RailRequest, RailResult


class EcoCashRail(PaymentRail):
    name = "ecocash"

    async def create_payment(self, request: RailRequest) -> RailResult:
        if not settings.is_production:
            return RailResult(
                external_reference=f"ecocash_sandbox_{uuid.uuid4().hex}",
                status="pending",
                raw={"mode": "sandbox-simulated", "payment_id": request.payment_id},
            )

        assert_live_funds_allowed()
        if not settings.ecocash_contract_confirmed or not settings.ecocash_contract_version:
            raise RuntimeError("EcoCash production contract has not been explicitly confirmed")
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
            token_data = token_response.json()
            token = str(token_data.get("access_token") or "").strip() if isinstance(token_data, dict) else ""
            if not token:
                raise RuntimeError("EcoCash OAuth response did not contain an access token")
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
            if not isinstance(data, dict):
                raise RuntimeError("EcoCash payment response was not a JSON object")
            external_ref = str(data.get("reference") or data.get("id") or "").strip()
            status = str(data.get("status") or "").strip().lower()
            if not external_ref or not status:
                raise RuntimeError("EcoCash payment response is missing reference or status")
            return RailResult(external_reference=external_ref, status=status, raw=data)
