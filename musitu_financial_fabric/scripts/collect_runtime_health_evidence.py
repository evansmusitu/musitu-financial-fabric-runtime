from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.component_registry import COMPONENTS, probe_components

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_OCI_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCHEMA_VERSION = "mff.required-runtime-health.v1"
_ALLOWED_ROW_FIELDS = ("key", "name", "kind", "required", "state", "status_code", "error")


def _clean_target_environment_id(value: str) -> str:
    target = str(value or "").strip()
    if not target:
        raise ValueError("target environment identity is required")
    if len(target) > 256 or any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
        raise ValueError("target environment identity is malformed")
    return target


def _clean_commit_sha(value: str) -> str:
    commit = str(value or "").strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(commit):
        raise ValueError("runtime commit must be an exact 40-hex Git commit SHA")
    return commit


def _clean_image_digest(value: str) -> str:
    digest = str(value or "").strip().lower()
    if not _OCI_DIGEST_RE.fullmatch(digest):
        raise ValueError("running image digest must be an exact sha256:<64-hex> OCI digest")
    return digest


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, separators=(",", ": ")) + "\n").encode("utf-8")


def _safe_component_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _ALLOWED_ROW_FIELDS if key in row}


def _expected_required_runtime_keys(components: Iterable[Any] = COMPONENTS) -> tuple[str, ...]:
    return tuple(sorted(c.key for c in components if c.required and c.kind == "runtime"))


def build_evidence(
    *,
    target_environment_id: str,
    commit_sha: str,
    image_digest: str,
    probe_result: dict[str, Any],
    observed_at: datetime | None = None,
    components: Iterable[Any] = COMPONENTS,
) -> dict[str, Any]:
    target = _clean_target_environment_id(target_environment_id)
    commit = _clean_commit_sha(commit_sha)
    digest = _clean_image_digest(image_digest)

    rows_raw = probe_result.get("components") if isinstance(probe_result, dict) else None
    rows = rows_raw if isinstance(rows_raw, list) else []
    safe_rows = [_safe_component_row(row) for row in rows if isinstance(row, dict)]

    expected_keys = _expected_required_runtime_keys(components)
    expected_set = set(expected_keys)
    required_runtime_rows = [
        row for row in safe_rows
        if row.get("required") is True and row.get("kind") == "runtime"
    ]
    observed_keys = [str(row.get("key", "")) for row in required_runtime_rows]
    observed_set = set(observed_keys)
    duplicate_keys = sorted({key for key in observed_keys if key and observed_keys.count(key) > 1})
    missing_keys = sorted(expected_set - observed_set)
    unexpected_keys = sorted(observed_set - expected_set)

    exact_inventory = (
        bool(expected_keys)
        and not duplicate_keys
        and not missing_keys
        and not unexpected_keys
        and len(required_runtime_rows) == len(expected_keys)
    )
    rows_healthy = exact_inventory and all(row.get("state") == "healthy" for row in required_runtime_rows)
    probe_summary_healthy = probe_result.get("all_required_runtime_healthy") is True if isinstance(probe_result, dict) else False
    all_healthy = bool(rows_healthy and probe_summary_healthy)

    timestamp = observed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("observed_at must include timezone information")
    timestamp = timestamp.astimezone(timezone.utc)

    return {
        "schema_version": _SCHEMA_VERSION,
        "target_environment_id": target,
        "observed_at": timestamp.isoformat().replace("+00:00", "Z"),
        "release": {
            "commit_sha": commit,
            "image_digest": digest,
        },
        "result": {
            "status": "passed" if all_healthy else "failed",
            "all_required_runtime_healthy": all_healthy,
            "expected_required_runtime_count": len(expected_keys),
            "observed_required_runtime_count": len(required_runtime_rows),
            "missing_required_runtime_keys": missing_keys,
            "unexpected_required_runtime_keys": unexpected_keys,
            "duplicate_required_runtime_keys": duplicate_keys,
        },
        "components": safe_rows,
        "notes": (
            "This artifact proves only observed required-runtime health for the bound target/build. "
            "It does not create or imply regulatory, sponsor-bank, rail-provider, data-protection, "
            "independent-security, monitoring, backup/restore, reconciliation, kill-control, or live-funds authorization."
        ),
    }


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def persist_evidence(output_path: Path, evidence: dict[str, Any]) -> tuple[str, Path, Path]:
    raw = _canonical_json_bytes(evidence)
    digest = hashlib.sha256(raw).hexdigest()
    _write_atomic(output_path, raw)

    sha_path = output_path.with_name(output_path.name + ".sha256")
    _write_atomic(sha_path, f"{digest}  {output_path.name}\n".encode("utf-8"))

    fragment = {
        "required_runtime_health": {
            "status": "passed" if evidence["result"]["all_required_runtime_healthy"] else "failed",
            "evidence_ref": f"sha256:{digest}",
            "artifact": output_path.name,
        }
    }
    fragment_path = output_path.with_name(output_path.name + ".manifest-fragment.json")
    _write_atomic(fragment_path, _canonical_json_bytes(fragment))
    return digest, sha_path, fragment_path


async def collect_and_persist(
    *,
    output_path: Path,
    target_environment_id: str,
    commit_sha: str,
    image_digest: str,
) -> tuple[int, dict[str, Any], str]:
    probe_result = await probe_components()
    evidence = build_evidence(
        target_environment_id=target_environment_id,
        commit_sha=commit_sha,
        image_digest=image_digest,
        probe_result=probe_result,
    )
    digest, _, _ = persist_evidence(output_path, evidence)
    return (0 if evidence["result"]["all_required_runtime_healthy"] else 1), evidence, digest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect fail-closed, target-bound evidence for all required MUSITU Financial Fabric runtime components."
    )
    parser.add_argument(
        "--output",
        default="runtime-health-evidence.json",
        help="JSON evidence output path (default: runtime-health-evidence.json)",
    )
    parser.add_argument(
        "--target-environment-id",
        default=os.getenv("MUSITU_TARGET_ENVIRONMENT_ID", ""),
        help="Immutable target ID; defaults to MUSITU_TARGET_ENVIRONMENT_ID",
    )
    parser.add_argument(
        "--commit-sha",
        default=os.getenv("MUSITU_BUILD_COMMIT", ""),
        help="Exact running Git commit; defaults to MUSITU_BUILD_COMMIT",
    )
    parser.add_argument(
        "--image-digest",
        default=os.getenv("MUSITU_RELEASE_IMAGE_DIGEST", ""),
        help="Exact running OCI digest; defaults to MUSITU_RELEASE_IMAGE_DIGEST",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        code, evidence, digest = asyncio.run(collect_and_persist(
            output_path=Path(args.output),
            target_environment_id=args.target_environment_id,
            commit_sha=args.commit_sha,
            image_digest=args.image_digest,
        ))
    except ValueError as exc:
        print(f"runtime-health-evidence: invalid identity: {exc}")
        return 2

    print(f"runtime-health-evidence: {evidence['result']['status']} sha256:{digest}")
    if code:
        missing = evidence["result"]["missing_required_runtime_keys"]
        unhealthy = [
            row.get("key") for row in evidence["components"]
            if row.get("required") is True and row.get("kind") == "runtime" and row.get("state") != "healthy"
        ]
        print(f"runtime-health-evidence: missing={missing} unhealthy={unhealthy}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
