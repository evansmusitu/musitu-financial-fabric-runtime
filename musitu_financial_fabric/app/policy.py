from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    reason: str


def evaluate_payment_policy(*, amount_minor: int, currency: str, rail: str, max_amount_minor: int) -> PolicyDecision:
    if amount_minor <= 0:
        return PolicyDecision(False, "amount_non_positive")
    if amount_minor > max_amount_minor:
        return PolicyDecision(False, "amount_over_limit")
    if len(currency) != 3 or not currency.isalpha():
        return PolicyDecision(False, "invalid_currency")
    if rail not in {"internal", "ecocash", "bank", "card", "stablecoin"}:
        return PolicyDecision(False, "rail_not_allowed")
    return PolicyDecision(True, "allow")
