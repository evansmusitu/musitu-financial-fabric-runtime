from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import Settings, settings


class ProductionGateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionCheck:
    key: str
    ok: bool
    category: str
    message: str


_REQUIRED_EVIDENCE = ("regulator", "sponsor_bank", "data_protection", "independent_security", "rail_provider")
_PRODUCTION_IMPLEMENTED_RAILS = {"ecocash"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SECURE_POSTGRES_SSLMODES = {"require", "verify-ca", "verify-full"}


def _parsed_service_url(value: str):
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        return None
    return parsed


def _secure_or_loopback_service_url(value: str) -> bool:
    parsed = _parsed_service_url(value)
    if parsed is None:
        return False
    if parsed.scheme.lower() == "https":
        return True
    return parsed.scheme.lower() == "http" and parsed.hostname.lower() in _LOOPBACK_HOSTS


def _secure_external_url(value: str) -> bool:
    parsed = _parsed_service_url(value)
    return bool(parsed is not None and parsed.scheme.lower() == "https")


def _postgres_transport_secure(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    if parsed.scheme.lower() not in {"postgresql", "postgres"} or not parsed.hostname:
        return False
    if parsed.hostname.lower() in _LOOPBACK_HOSTS:
        return True
    query = parse_qs(parsed.query)
    sslmode = str((query.get("sslmode") or [""])[0]).strip().lower()
    return sslmode in _SECURE_POSTGRES_SSLMODES


def _authorization_manifest(cfg: Settings) -> tuple[dict[str, Any] | None, str | None]:
    if not cfg.authorization_manifest_path or not cfg.authorization_manifest_sha256:
        return None, "authorization evidence manifest is not configured"
    if not _SHA256_RE.fullmatch(cfg.authorization_manifest_sha256):
        return None, "authorization manifest SHA-256 is malformed"
    path = Path(cfg.authorization_manifest_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"authorization manifest unavailable: {type(exc).__name__}"
    actual = hashlib.sha256(raw).hexdigest()
    if actual != cfg.authorization_manifest_sha256:
        return None, "authorization manifest SHA-256 mismatch"
    try:
        data = json.loads(raw)
    except Exception:
        return None, "authorization manifest is not valid JSON"
    if not isinstance(data, dict):
        return None, "authorization manifest root must be an object"
    return data, None


def _evidence_checks(cfg: Settings) -> list[ProductionCheck]:
    manifest, error = _authorization_manifest(cfg)
    if error:
        return [ProductionCheck("authorization_manifest", False, "external", error)]
    assert manifest is not None
    checks = [ProductionCheck("authorization_manifest", True, "external", "pinned authorization manifest verified")]
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict):
        return checks + [ProductionCheck("authorization_evidence", False, "external", "manifest evidence object missing")]

    for key in _REQUIRED_EVIDENCE:
        row = evidence.get(key)
        ok = (
            isinstance(row, dict)
            and row.get("status") == "approved"
            and isinstance(row.get("evidence_ref"), str)
            and bool(row["evidence_ref"].strip())
        )
        checks.append(ProductionCheck(
            f"evidence_{key}",
            bool(ok),
            "external",
            f"{key} approval evidence {'present' if ok else 'missing or not approved'}",
        ))

    scope = str(manifest.get("funds_scope", "")).lower()
    if cfg.production_mode == "pilot":
        scope_ok = scope in {"pilot", "production"}
        scope_message = "authorization scope permits controlled pilot funds activity"
    elif cfg.production_mode == "live":
        scope_ok = scope == "production"
        scope_message = "authorization scope permits unrestricted production funds activity"
    else:
        scope_ok = False
        scope_message = "shadow mode can never be authorized for real-funds activity"
    checks.append(ProductionCheck(
        "authorized_funds_scope",
        scope_ok,
        "external",
        scope_message if scope_ok else f"authorization scope {scope or 'none'} does not permit runtime mode {cfg.production_mode}",
    ))

    launch_scope = manifest.get("launch_scope")
    if not isinstance(launch_scope, dict):
        checks.extend([
            ProductionCheck("authorized_rails", False, "external", "authorization launch_scope.rails is missing"),
            ProductionCheck("authorized_currencies", False, "external", "authorization launch_scope.currencies is missing"),
            ProductionCheck("authorized_single_payment_limit", False, "external", "authorization launch_scope.max_single_payment_minor is missing"),
        ])
    else:
        rails_raw = launch_scope.get("rails")
        currencies_raw = launch_scope.get("currencies")
        authorized_rails = {
            value.strip().lower()
            for value in rails_raw
            if isinstance(value, str) and value.strip()
        } if isinstance(rails_raw, list) else set()
        authorized_currencies = {
            value.strip().upper()
            for value in currencies_raw
            if isinstance(value, str) and value.strip()
        } if isinstance(currencies_raw, list) else set()
        runtime_rails = set(cfg.production_enabled_rails)
        runtime_currencies = set(cfg.production_enabled_currencies)
        rails_ok = bool(runtime_rails) and bool(authorized_rails) and runtime_rails.issubset(authorized_rails)
        currencies_ok = bool(runtime_currencies) and bool(authorized_currencies) and runtime_currencies.issubset(authorized_currencies)
        try:
            authorized_max = int(launch_scope.get("max_single_payment_minor", 0))
        except (TypeError, ValueError):
            authorized_max = 0
        max_ok = authorized_max > 0 and 0 < cfg.max_single_payment_minor <= authorized_max
        checks.extend([
            ProductionCheck(
                "authorized_rails",
                rails_ok,
                "external",
                "runtime production rails are within the pinned authorization perimeter" if rails_ok else "runtime production rails exceed or lack the pinned authorization perimeter",
            ),
            ProductionCheck(
                "authorized_currencies",
                currencies_ok,
                "external",
                "runtime production currencies are within the pinned authorization perimeter" if currencies_ok else "runtime production currencies exceed or lack the pinned authorization perimeter",
            ),
            ProductionCheck(
                "authorized_single_payment_limit",
                max_ok,
                "external",
                "runtime single-payment ceiling does not exceed the pinned authorization perimeter" if max_ok else "runtime single-payment ceiling exceeds or lacks the pinned authorization perimeter",
            ),
        ])

    expires_at = manifest.get("expires_at")
    try:
        if not expires_at:
            raise ValueError("missing expiry")
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("expiry must include timezone")
        expiry_ok = expiry > datetime.now(timezone.utc)
    except Exception:
        expiry_ok = False
    checks.append(ProductionCheck(
        "authorization_not_expired",
        expiry_ok,
        "external",
        "authorization evidence is within its explicit validity period" if expiry_ok else "authorization expiry is missing, invalid, or expired",
    ))
    return checks


def production_checks(cfg: Settings = settings) -> list[ProductionCheck]:
    enabled_rails = set(cfg.production_enabled_rails)
    rails_ok = bool(enabled_rails) and enabled_rails.issubset(_PRODUCTION_IMPLEMENTED_RAILS)
    enabled_currencies = set(cfg.production_enabled_currencies)
    currencies_ok = bool(enabled_currencies) and all(len(code) == 3 and code.isalpha() and code == code.upper() for code in enabled_currencies)
    ecocash_enabled = "ecocash" in enabled_rails
    ecocash_configured = all([
        cfg.ecocash_api_base,
        cfg.ecocash_oauth_path,
        cfg.ecocash_payment_path,
        cfg.ecocash_callback_url,
        cfg.ecocash_client_id,
        cfg.ecocash_client_secret,
    ])
    metadata_transport_ok = _postgres_transport_secure(cfg.metadata_db_url)
    introspection_transport_ok = _secure_or_loopback_service_url(cfg.auth_introspection_url)
    authz_transport_ok = _secure_or_loopback_service_url(cfg.authz_gate_url)
    risk_transport_ok = _secure_or_loopback_service_url(cfg.risk_gate_url)
    ecocash_transport_ok = (not ecocash_enabled) or (
        _secure_external_url(cfg.ecocash_api_base) and _secure_external_url(cfg.ecocash_callback_url)
    )

    checks = [
        ProductionCheck("environment", cfg.environment == "production", "software", "runtime environment is production"),
        ProductionCheck(
            "production_mode",
            cfg.production_mode in {"pilot", "live"},
            "software",
            "live funds require pilot or live mode; shadow mode is observation-only",
        ),
        ProductionCheck("live_funds_flag", cfg.live_funds_enabled, "software", "live funds flag is explicitly enabled"),
        ProductionCheck("metadata_postgres", cfg.uses_postgres, "software", "production metadata store is PostgreSQL"),
        ProductionCheck("metadata_transport", metadata_transport_ok, "software", "remote PostgreSQL requires explicit TLS; loopback is allowed for local deployment/testing"),
        ProductionCheck("ledger_tigerbeetle", cfg.ledger_backend == "tigerbeetle", "software", "monetary truth backend is TigerBeetle"),
        ProductionCheck("tigerbeetle_addresses", bool(cfg.tigerbeetle_addresses), "software", "TigerBeetle replica addresses are configured"),
        ProductionCheck(
            "tigerbeetle_cluster_id",
            0 < cfg.tigerbeetle_cluster_id < (1 << 128),
            "software",
            "production TigerBeetle cluster ID is a nonzero u128 and does not use the reserved test cluster",
        ),
        ProductionCheck(
            "production_rails",
            rails_ok,
            "software",
            "only explicitly enabled, implemented production rails may initiate funds movement",
        ),
        ProductionCheck(
            "production_currencies",
            currencies_ok,
            "software",
            "production currencies are explicitly configured as valid ISO-style three-letter codes",
        ),
        ProductionCheck(
            "single_payment_limit",
            cfg.max_single_payment_minor > 0,
            "software",
            "single-payment ceiling is explicitly positive",
        ),
        ProductionCheck(
            "ecocash_contract",
            (not ecocash_enabled) or (cfg.ecocash_contract_confirmed and bool(cfg.ecocash_contract_version)),
            "external",
            "EcoCash production contract is explicitly confirmed when the rail is enabled",
        ),
        ProductionCheck(
            "ecocash_connector",
            (not ecocash_enabled) or ecocash_configured,
            "software",
            "EcoCash production credentials, endpoints, and MUSITU provider callback are present when the rail is enabled",
        ),
        ProductionCheck("ecocash_transport", ecocash_transport_ok, "software", "EcoCash production API and MUSITU provider callback use HTTPS"),
        ProductionCheck(
            "api_auth",
            all([cfg.auth_introspection_url, cfg.auth_client_id, cfg.auth_client_secret]),
            "software",
            "production bearer-token introspection is configured",
        ),
        ProductionCheck("auth_introspection_transport", introspection_transport_ok, "software", "identity introspection uses HTTPS or a loopback sidecar"),
        ProductionCheck("authz_gate", bool(cfg.authz_gate_url), "software", "OpenFGA/OPA authorization decision gate is configured"),
        ProductionCheck("authz_transport", authz_transport_ok, "software", "authorization gate uses HTTPS or a loopback sidecar"),
        ProductionCheck("risk_gate", bool(cfg.risk_gate_url), "software", "production risk/compliance decision gate is configured"),
        ProductionCheck("risk_transport", risk_transport_ok, "software", "risk gate uses HTTPS or a loopback sidecar"),
        ProductionCheck(
            "webhook_secret",
            len(cfg.webhook_secret) >= 32 and cfg.webhook_secret != "sandbox-secret-change-me",
            "software",
            "provider webhook secret is non-default and at least 32 characters",
        ),
    ]
    checks.extend(_evidence_checks(cfg))
    return checks


def production_readiness(cfg: Settings = settings) -> dict[str, Any]:
    checks = production_checks(cfg)
    return {
        "ready_for_live_funds": bool(checks) and all(c.ok for c in checks),
        "checks": [asdict(c) for c in checks],
    }


def assert_live_funds_allowed(cfg: Settings = settings) -> None:
    if not cfg.is_production:
        raise ProductionGateError("live funds are forbidden outside the production environment")
    result = production_readiness(cfg)
    if not result["ready_for_live_funds"]:
        failed = [row["key"] for row in result["checks"] if not row["ok"]]
        raise ProductionGateError("production live-funds gate is closed: " + ",".join(failed))


def enforce_safe_startup(cfg: Settings = settings) -> None:
    if cfg.environment not in {"sandbox", "test", "development", "production"}:
        raise ProductionGateError(f"unsupported MUSITU_ENV: {cfg.environment}")
    if cfg.is_production:
        if cfg.production_mode not in {"shadow", "pilot", "live"}:
            raise ProductionGateError("production startup requires MUSITU_PRODUCTION_MODE=shadow, pilot, or live")
        if not cfg.uses_postgres:
            raise ProductionGateError("production startup requires MUSITU_METADATA_DB_URL pointing to PostgreSQL")
        if not _postgres_transport_secure(cfg.metadata_db_url):
            raise ProductionGateError("production startup requires explicit TLS for remote PostgreSQL or loopback transport")
        if cfg.ledger_backend != "tigerbeetle":
            raise ProductionGateError("production startup requires MUSITU_LEDGER_BACKEND=tigerbeetle")
        if not cfg.tigerbeetle_addresses:
            raise ProductionGateError("production startup requires TigerBeetle replica addresses")
        if not (0 < cfg.tigerbeetle_cluster_id < (1 << 128)):
            raise ProductionGateError("production startup requires a nonzero TigerBeetle cluster ID; cluster 0 is reserved for testing and benchmarking")
        if not all([cfg.auth_introspection_url, cfg.auth_client_id, cfg.auth_client_secret]):
            raise ProductionGateError("production startup requires bearer-token introspection configuration")
        if not _secure_or_loopback_service_url(cfg.auth_introspection_url):
            raise ProductionGateError("production identity introspection requires HTTPS or a loopback sidecar")
        if not cfg.authz_gate_url:
            raise ProductionGateError("production startup requires an OpenFGA/OPA authorization decision gate")
        if not _secure_or_loopback_service_url(cfg.authz_gate_url):
            raise ProductionGateError("production authorization gate requires HTTPS or a loopback sidecar")
        if not cfg.risk_gate_url:
            raise ProductionGateError("production startup requires a risk/compliance decision gate")
        if not _secure_or_loopback_service_url(cfg.risk_gate_url):
            raise ProductionGateError("production risk gate requires HTTPS or a loopback sidecar")
        if "ecocash" in set(cfg.production_enabled_rails):
            if cfg.ecocash_api_base and not _secure_external_url(cfg.ecocash_api_base):
                raise ProductionGateError("production EcoCash API requires HTTPS")
            if cfg.ecocash_callback_url and not _secure_external_url(cfg.ecocash_callback_url):
                raise ProductionGateError("production EcoCash callback requires HTTPS")
        if len(cfg.webhook_secret) < 32 or cfg.webhook_secret == "sandbox-secret-change-me":
            raise ProductionGateError("production startup requires a strong non-default webhook secret")
        if cfg.live_funds_enabled:
            assert_live_funds_allowed(cfg)