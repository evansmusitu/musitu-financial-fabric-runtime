from __future__ import annotations

import uuid

from ..config import settings
from .base import PaymentRail, RailRequest, RailResult


class ConfiguredExternalRail(PaymentRail):
    def __init__(self, name: str):
        self.name = name

    async def create_payment(self, request: RailRequest) -> RailResult:
        if settings.environment != "production":
            return RailResult(
                external_reference=f"{self.name}_sandbox_{uuid.uuid4().hex}",
                status="pending",
                raw={"mode": "sandbox-reference", "rail": self.name, "payment_id": request.payment_id},
            )
        if not settings.live_funds_enabled:
            raise RuntimeError("Production live-funds gate is disabled")
        raise RuntimeError(f"{self.name} production connector is mandatory but not configured")
