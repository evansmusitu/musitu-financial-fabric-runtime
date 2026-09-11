from __future__ import annotations

from dataclasses import dataclass

from .config import settings


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    reason: str


_PRODUCTION_IMPLEMENTED_RAILS = {"ecocash"}


def evaluate_payment_policy(*, amount_minor: int, currency: str, rail: str, max_amount_minor: int) -> PolicyDecision:
    if amount_minor <= 0:
        return PolicyDecision(False, "amount_non_positive")
    if amount_minor > max_amount_minor:
        return PolicyDecision(False, "amount_over_limit")
    if len(currency) != 3 or not currency.isalpha():
        return PolicyDecision(False, "invalid_currency")
    if rail not in {"internal", "ecocash", "bank", "card", "stablecoin"}:
        return PolicyDecision(False, "rail_not_allowed")

    if settings.is_production:
        enabled = set(settings.production_enabled_rails)
        enabled_currencies = set(settings.production_enabled_currencies)
        if currency.upper() not in enabled_currencies:
            return PolicyDecision(False, "currency_not_production_enabled")
        if rail not in enabled:
            return PolicyDecision(False, "rail_not_production_enabled")
        if rail not in _PRODUCTION_IMPLEMENTED_RAILS:
            return PolicyDecision(False, "production_connector_unavailable")
        if rail == "ecocash":
            if not settings.ecocash_contract_confirmed or not settings.ecocash_contract_version:
                return PolicyDecision(False, "ecocash_contract_unconfirmed")
            required = [
                settings.ecocash_api_base,
                settings.ecocash_oauth_path,
                settings.ecocash_payment_path,
                settings.ecocash_client_id,
                settings.ecocash_client_secret,
            ]
            if not all(required):
                return PolicyDecision(False, "ecocash_connector_incomplete")

    return PolicyDecision(True, "allow")
