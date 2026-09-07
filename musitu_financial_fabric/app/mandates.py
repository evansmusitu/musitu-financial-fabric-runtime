from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentMandate:
    mandate_id: str
    principal_id: str
    agent_id: str
    max_per_payment_minor: int
    max_daily_minor: int
    currency: str
    allowed_rails: tuple[str, ...]


def authorize_mandate(mandate: AgentMandate, *, amount_minor: int, currency: str, rail: str) -> tuple[bool, str]:
    if currency.upper() != mandate.currency.upper():
        return False, "currency_not_authorized"
    if amount_minor > mandate.max_per_payment_minor:
        return False, "per_payment_limit_exceeded"
    if rail not in mandate.allowed_rails:
        return False, "rail_not_authorized"
    return True, "authorized"
