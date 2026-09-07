from __future__ import annotations

from .base import PaymentRail, RailRequest, RailResult


class InternalRail(PaymentRail):
    name = "internal"

    async def create_payment(self, request: RailRequest) -> RailResult:
        return RailResult(external_reference=request.payment_id, status="pending", raw={"mode": "internal"})
