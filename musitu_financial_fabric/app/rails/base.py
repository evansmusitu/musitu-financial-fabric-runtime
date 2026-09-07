from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RailRequest:
    payment_id: str
    amount_minor: int
    currency: str
    payer_ref: str | None
    description: str | None
    callback_url: str | None = None


@dataclass
class RailResult:
    external_reference: str
    status: str
    raw: dict


class PaymentRail(ABC):
    name: str

    @abstractmethod
    async def create_payment(self, request: RailRequest) -> RailResult:
        raise NotImplementedError
