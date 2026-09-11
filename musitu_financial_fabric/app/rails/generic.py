from __future__ import annotations

import uuid

from ..config import settings
from ..production import assert_live_funds_allowed
from .base import PaymentRail, RailRequest, RailResult


class ConfiguredExternalRail(PaymentRail):
    def __init__(self, name: str):
        self.name = name

    async def create_payment(self, request: RailRequest) -> RailResult:
        if not settings.is_production:
            return RailResult(
                external_reference=f"{self.name}_sandbox_{uuid.uuid4().hex}",
                status="pending",
                raw={"mode": "sandbox-reference", "rail": self.name, "payment_id": request.payment_id},
            )
        assert_live_funds_allowed()
        raise RuntimeError(f"{self.name} production connector is mandatory but not configured")
