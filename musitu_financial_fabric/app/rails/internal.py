from __future__ import annotations

from ..config import settings
from ..production import assert_live_funds_allowed
from .base import PaymentRail, RailRequest, RailResult


class InternalRail(PaymentRail):
    name = "internal"

    async def create_payment(self, request: RailRequest) -> RailResult:
        if settings.is_production:
            assert_live_funds_allowed()
        return RailResult(external_reference=request.payment_id, status="pending", raw={"mode": "internal"})
