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
_PG_BIGINT_MAX = (1 << 63) - 1
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_OCI_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_DEPLOYMENT_EVIDENCE = (
    "dark_deployment",
    "monitoring_alerting",
    "postgres_backup_restore",
    "tigerbeetle_recovery",
    "provider_reconciliation",
    "activation_rollback_drill",
)
_REQUIRED_INDEPENDENT_KILL_CONTROLS = ("network", "provider", "settlement")


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


def _relative_provider_path(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return bool(not parsed.scheme and not parsed.netloc and parsed.path and not value.startswith("//"))


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


def _deployment_evidence_manifest(cfg: Settings) -> tuple[dict[str, Any] | None, str | None]:
    if not cfg.deployment_evidence_manifest_path or not cfg.deployment_evidence_manifest_sha256:
        return None, "target deployment evidence manifest is not configured"
    if not _SHA256_RE.fullmatch(cfg.deployment_evidence_manifest_sha256):
        return None, "target deployment evidence manifest SHA-256 is malformed"
    path = Path(cfg.deployment_evidence_manifest_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"target deployment evidence manifest unavailable: {type(exc).__name__}"
    actual = hashlib.sha256(raw).hexdigest()
    if actual != cfg.deployment_evidence_manifest_sha256:
        return None, "target deployment evidence manifest SHA-256 mismatch"
    try:
        data = json.loads(raw)
    except Exception:
        return None, "target deployment evidence manifest is not valid JSON"
    if not isinstance(data, dict):
        return None, "target deployment evidence manifest root must be an object"
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


def _deployment_evidence_checks(cfg: Settings) -> list[ProductionCheck]:
    manifest, error = _deployment_evidence_manifest(cfg)
    if error:
        return [ProductionCheck("deployment_evidence_manifest", False, "deployment", error)]
    assert manifest is not None

    checks = [ProductionCheck(
        "deployment_evidence_manifest",
        True,
        "deployment",
        "byte-pinned target deployment evidence manifest verified",
    )]

    target_environment_id = manifest.get("target_environment_id")
    target_ok = isinstance(target_environment_id, str) and bool(target_environment_id.strip())
    checks.append(ProductionCheck(
        "deployment_target_identity",
        target_ok,
        "deployment",
        "target production environment has an explicit immutable evidence identity" if target_ok else "target production environment identity is missing",
    ))

    release = manifest.get("release")
    if not isinstance(release, dict):
        checks.extend([
            ProductionCheck("deployment_release_commit", False, "deployment", "target deployment release.commit_sha is missing"),
            ProductionCheck("deployment_release_image", False, "deployment", "target deployment release.image_digest is missing"),
            ProductionCheck("deployment_rollback_image", False, "deployment", "target deployment release.rollback_image_digest is missing"),
            ProductionCheck("deployment_authorization_binding", False, "deployment", "target deployment is not bound to the external authorization manifest"),
        ])
    else:
        manifest_commit = str(release.get("commit_sha", "")).strip().lower()
        manifest_image = str(release.get("image_digest", "")).strip().lower()
        rollback_image = str(release.get("rollback_image_digest", "")).strip().lower()
        auth_pin = str(release.get("authorization_manifest_sha256", "")).strip().lower()
        commit_ok = (
            bool(cfg.build_commit)
            and bool(_COMMIT_SHA_RE.fullmatch(cfg.build_commit))
            and manifest_commit == cfg.build_commit
        )
        image_ok = (
            bool(cfg.release_image_digest)
            and bool(_OCI_DIGEST_RE.fullmatch(cfg.release_image_digest))
            and manifest_image == cfg.release_image_digest
        )
        rollback_ok = bool(_OCI_DIGEST_RE.fullmatch(rollback_image)) and rollback_image != manifest_image
        auth_binding_ok = (
            bool(_SHA256_RE.fullmatch(cfg.authorization_manifest_sha256))
            and auth_pin == cfg.authorization_manifest_sha256
        )
        checks.extend([
            ProductionCheck(
                "deployment_release_commit",
                commit_ok,
                "deployment",
                "target deployment evidence matches the running source revision" if commit_ok else "target deployment evidence does not match the running source revision",
            ),
            ProductionCheck(
                "deployment_release_image",
                image_ok,
                "deployment",
                "target deployment evidence matches the immutable running OCI digest" if image_ok else "target deployment evidence does not match the immutable running OCI digest",
            ),
            ProductionCheck(
                "deployment_rollback_image",
                rollback_ok,
                "deployment",
                "a distinct immutable rollback OCI digest is recorded" if rollback_ok else "a distinct immutable rollback OCI digest is missing or malformed",
            ),
            ProductionCheck(
                "deployment_authorization_binding",
                auth_binding_ok,
                "deployment",
                "target deployment evidence is bound to the exact external authorization manifest" if auth_binding_ok else "target deployment evidence is not bound to the configured external authorization manifest",
            ),
        ])

    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict):
        checks.append(ProductionCheck("deployment_operational_evidence", False, "deployment", "target deployment evidence object is missing"))
    else:
        for key in _REQUIRED_DEPLOYMENT_EVIDENCE:
            row = evidence.get(key)
            ok = (
                isinstance(row, dict)
                and row.get("status") == "passed"
                and isinstance(row.get("evidence_ref"), str)
                and bool(row["evidence_ref"].strip())
            )
            checks.append(ProductionCheck(
                f"deployment_{key}",
                bool(ok),
                "deployment",
                f"{key} target-environment evidence {'passed' if ok else 'missing or not passed'}",
            ))

    kill_controls = manifest.get("independent_kill_controls")
    if not isinstance(kill_controls, dict):
        checks.append(ProductionCheck(
            "independent_kill_controls",
            False,
            "deployment",
            "independent network/provider/settlement kill-control evidence is missing",
        ))
    else:
        for key in _REQUIRED_INDEPENDENT_KILL_CONTROLS:
            row = kill_controls.get(key)
            ok = (
                isinstance(row, dict)
                and row.get("status") == "verified"
                and row.get("independent_of_application") is True
                and isinstance(row.get("evidence_ref"), str)
                and bool(row["evidence_ref"].strip())
            )
            checks.append(ProductionCheck(
                f"independent_kill_{key}",
                bool(ok),
                "deployment",
                f"independent {key} kill control {'verified' if ok else 'missing or not independently verified'}",
            ))

    now = datetime.now(timezone.utc)
    verified_at = manifest.get("verified_at")
    try:
        if not verified_at:
            raise ValueError("missing verified_at")
        verified = datetime.fromisoformat(str(verified_at).replace("Z", "+00:00"))
        if verified.tzinfo is None:
            raise ValueError("verified_at must include timezone")
        verified_ok = verified <= now
    except Exception:
        verified_ok = False
    checks.append(ProductionCheck(
        "deployment_verified_at",
        verified_ok,
        "deployment",
        "target deployment verification timestamp is valid" if verified_ok else "target deployment verification timestamp is missing, invalid, or in the future",
    ))

    expires_at = manifest.get("expires_at")
    try:
        if not expires_at:
            raise ValueError("missing expiry")
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("expiry must include timezone")
        expiry_ok = expiry > now
    except Exception:
        expiry_ok = False
    checks.append(ProductionCheck(
        "deployment_evidence_not_expired",
        expiry_ok,
        "deployment",
        "target deployment evidence is within its explicit validity period" if expiry_ok else "target deployment evidence expiry is missing, invalid, or expired",
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
    ecocash_paths_ok = (not ecocash_enabled) or (
        _relative_provider_path(cfg.ecocash_oauth_path)
        and _relative_provider_path(cfg.ecocash_payment_path)
    )
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
        ProductionCheck(
            "request_body_limit",
            cfg.max_request_body_bytes > 0,
            "software",
            "production request-body limit is explicitly positive",
        ),
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
            "tigerbeetle_account_code",
            0 < cfg.tigerbeetle_account_code <= 0xFFFF,
            "software",
            "TigerBeetle account code is a nonzero u16",
        ),
        ProductionCheck(
            "tigerbeetle_transfer_code",
            0 < cfg.tigerbeetle_transfer_code <= 0xFFFF,
            "software",
            "TigerBeetle transfer code is a nonzero u16",
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
            0 < cfg.max_single_payment_minor <= _PG_BIGINT_MAX,
            "software",
            "single-payment ceiling is positive and representable in PostgreSQL BIGINT",
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
        ProductionCheck(
            "ecocash_endpoint_paths",
            ecocash_paths_ok,
            "software",
            "EcoCash OAuth and payment endpoints remain relative to the pinned provider host",
        ),
        ProductionCheck("ecocash_transport", ecocash_transport_ok, "software", "EcoCash production API and MUSITU provider callback use HTTPS"),
        ProductionCheck(
            "api_auth",
            all([cfg.auth_introspection_url, cfg.auth_client_id, cfg.auth_client_secret]),
            "software",
            "production bearer-token introspection is configured",
        ),
        ProductionCheck(
            "auth_required_scope",
            bool(cfg.auth_required_scope.strip()),
            "software",
            "production bearer tokens must satisfy a nonempty required scope",
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
        ProductionCheck(
            "release_commit",
            bool(_COMMIT_SHA_RE.fullmatch(cfg.build_commit)),
            "software",
            "running production artifact exposes an exact 40-hex source revision",
        ),
        ProductionCheck(
            "release_image_digest",
            bool(_OCI_DIGEST_RE.fullmatch(cfg.release_image_digest)),
            "software",
            "running production artifact is identified by an immutable sha256 OCI digest",
        ),
    ]
    checks.extend(_evidence_checks(cfg))
    checks.extend(_deployment_evidence_checks(cfg))
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
        if cfg.max_request_body_bytes <= 0:
            raise ProductionGateError("production startup requires a positive request body limit")
        if not (0 < cfg.max_single_payment_minor <= _PG_BIGINT_MAX):
            raise ProductionGateError("production startup requires a positive single-payment limit representable in PostgreSQL BIGINT")
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
        if not (0 < cfg.tigerbeetle_account_code <= 0xFFFF):
            raise ProductionGateError("production startup requires a nonzero TigerBeetle account code within u16 range")
        if not (0 < cfg.tigerbeetle_transfer_code <= 0xFFFF):
            raise ProductionGateError("production startup requires a nonzero TigerBeetle transfer code within u16 range")
        if not all([cfg.auth_introspection_url, cfg.auth_client_id, cfg.auth_client_secret]):
            raise ProductionGateError("production startup requires bearer-token introspection configuration")
        if not cfg.auth_required_scope.strip():
            raise ProductionGateError("production startup requires a nonempty bearer-token scope")
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
            if cfg.ecocash_oauth_path and not _relative_provider_path(cfg.ecocash_oauth_path):
                raise ProductionGateError("production EcoCash OAuth endpoint must be a relative path on the pinned provider host")
            if cfg.ecocash_payment_path and not _relative_provider_path(cfg.ecocash_payment_path):
                raise ProductionGateError("production EcoCash payment endpoint must be a relative path on the pinned provider host")
        if len(cfg.webhook_secret) < 32 or cfg.webhook_secret == "sandbox-secret-change-me":
            raise ProductionGateError("production startup requires a strong non-default webhook secret")
        if cfg.live_funds_enabled:
            assert_live_funds_allowed(cfg)
