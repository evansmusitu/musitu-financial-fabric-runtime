from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

    expires_at = manifest.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            ok = expiry > datetime.now(timezone.utc)
        except Exception:
            ok = False
        checks.append(ProductionCheck(
            "authorization_not_expired",
            ok,
            "external",
            "authorization evidence is within validity period" if ok else "authorization evidence is expired or invalid",
        ))
    return checks


def production_checks(cfg: Settings = settings) -> list[ProductionCheck]:
    enabled_rails = set(cfg.production_enabled_rails)
    rails_ok = bool(enabled_rails) and enabled_rails.issubset(_PRODUCTION_IMPLEMENTED_RAILS)
    ecocash_enabled = "ecocash" in enabled_rails
    ecocash_configured = all([
        cfg.ecocash_api_base,
        cfg.ecocash_oauth_path,
        cfg.ecocash_payment_path,
        cfg.ecocash_client_id,
        cfg.ecocash_client_secret,
    ])

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
        ProductionCheck("ledger_tigerbeetle", cfg.ledger_backend == "tigerbeetle", "software", "monetary truth backend is TigerBeetle"),
        ProductionCheck("tigerbeetle_addresses", bool(cfg.tigerbeetle_addresses), "software", "TigerBeetle replica addresses are configured"),
        ProductionCheck(
            "production_rails",
            rails_ok,
            "software",
            "only explicitly enabled, implemented production rails may initiate funds movement",
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
            "EcoCash production credentials and exact endpoint configuration are present when the rail is enabled",
        ),
        ProductionCheck(
            "api_auth",
            all([cfg.auth_introspection_url, cfg.auth_client_id, cfg.auth_client_secret]),
            "software",
            "production bearer-token introspection is configured",
        ),
        ProductionCheck("authz_gate", bool(cfg.authz_gate_url), "software", "OpenFGA/OPA authorization decision gate is configured"),
        ProductionCheck("risk_gate", bool(cfg.risk_gate_url), "software", "production risk/compliance decision gate is configured"),
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
        if cfg.ledger_backend != "tigerbeetle":
            raise ProductionGateError("production startup requires MUSITU_LEDGER_BACKEND=tigerbeetle")
        if not cfg.tigerbeetle_addresses:
            raise ProductionGateError("production startup requires TigerBeetle replica addresses")
        if not all([cfg.auth_introspection_url, cfg.auth_client_id, cfg.auth_client_secret]):
            raise ProductionGateError("production startup requires bearer-token introspection configuration")
        if not cfg.authz_gate_url:
            raise ProductionGateError("production startup requires an OpenFGA/OPA authorization decision gate")
        if not cfg.risk_gate_url:
            raise ProductionGateError("production startup requires a risk/compliance decision gate")
        if len(cfg.webhook_secret) < 32 or cfg.webhook_secret == "sandbox-secret-change-me":
            raise ProductionGateError("production startup requires a strong non-default webhook secret")
        if cfg.live_funds_enabled:
            assert_live_funds_allowed(cfg)
