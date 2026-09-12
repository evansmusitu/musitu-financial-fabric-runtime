from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
SOURCE_POLICY = TARGET / "kubernetes-manifest-semantics-policy.json"
POLICY = TARGET / "kubernetes-manifest-security-hardening-policy.json"

EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.kubernetes-manifest-security-hardening-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.kubernetes-manifest-semantics-policy.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob")
ALLOWED_ADDED_CAPABILITIES = ("NET_BIND_SERVICE",)
ALLOWED_SECCOMP = ("RuntimeDefault", "Localhost")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_file(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    relative = Path(value.strip())
    if relative.is_absolute():
        return None
    root = ROOT.resolve()
    resolved = (ROOT / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _policy_errors(policy: object, source_policy: object) -> list[str]:
    if not isinstance(policy, dict):
        return ["Kubernetes manifest security hardening policy root must be an object"]
    expected = {
        "schema_version": POLICY_SCHEMA,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "source_manifest_semantics_policy_schema_version": SOURCE_POLICY_SCHEMA,
        "require_primary_digest_in_regular_container": True,
        "allowed_added_capabilities": list(ALLOWED_ADDED_CAPABILITIES),
        "reject_run_as_user_zero": True,
        "validate_seccomp_localhost_profile": True,
    }
    errors = [
        f"Kubernetes manifest security hardening policy {field} is invalid"
        for field, value in expected.items()
        if policy.get(field) != value
    ]
    if not isinstance(source_policy, dict):
        return errors + ["source Kubernetes manifest semantics policy root must be an object"]
    if source_policy.get("schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("source Kubernetes manifest semantics policy schema drifted")
    if source_policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("source Kubernetes manifest semantics policy is not anchored to the sealed runtime release")
    if source_policy.get("allowed_seccomp_types") != list(ALLOWED_SECCOMP):
        errors.append("source Kubernetes manifest semantics seccomp policy drifted")
    return errors


def _documents(payload: object) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(payload, dict):
        return [], ["rendered manifest root must be a Kubernetes object"]
    if payload.get("kind") == "List":
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return [], ["Kubernetes List must contain a non-empty items array"]
        docs: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, item in enumerate(items):
            if isinstance(item, dict):
                docs.append(item)
            else:
                errors.append(f"Kubernetes List item {index} must be an object")
        return docs, errors
    return [payload], []


def _pod_spec(obj: dict[str, Any]) -> dict[str, Any] | None:
    kind = obj.get("kind")
    spec = obj.get("spec")
    if not isinstance(spec, dict):
        return None
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        template = spec.get("template")
        return template.get("spec") if isinstance(template, dict) and isinstance(template.get("spec"), dict) else None
    if kind == "CronJob":
        job_template = spec.get("jobTemplate")
        job_spec = job_template.get("spec") if isinstance(job_template, dict) else None
        template = job_spec.get("template") if isinstance(job_spec, dict) else None
        return template.get("spec") if isinstance(template, dict) and isinstance(template.get("spec"), dict) else None
    return None


def _seccomp_errors(profile: object, label: str) -> list[str]:
    if profile is None:
        return []
    if not isinstance(profile, dict):
        return [f"{label} seccompProfile must be an object"]
    profile_type = profile.get("type")
    localhost_profile = profile.get("localhostProfile")
    if profile_type == "Localhost":
        if not isinstance(localhost_profile, str) or not localhost_profile.strip():
            return [f"{label} Localhost seccompProfile requires localhostProfile"]
        value = localhost_profile.strip()
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts:
            return [f"{label} localhostProfile must be a descending relative path"]
    elif localhost_profile not in (None, ""):
        return [f"{label} localhostProfile is only valid with seccomp type Localhost"]
    return []


def _pod_security_errors(pod_spec: dict[str, Any], digest: str, workload_label: str) -> list[str]:
    errors: list[str] = []
    pod_security = pod_spec.get("securityContext")
    pod_security = pod_security if isinstance(pod_security, dict) else {}
    if pod_security.get("runAsUser") == 0:
        errors.append(f"{workload_label} pod securityContext.runAsUser must not be 0")
    errors.extend(_seccomp_errors(pod_security.get("seccompProfile"), f"{workload_label} pod"))

    regular = pod_spec.get("containers")
    if not isinstance(regular, list) or not regular:
        errors.append(f"{workload_label} must contain at least one regular container")
        regular = []
    regular_primary_matches = 0
    for index, container in enumerate(regular):
        if not isinstance(container, dict):
            errors.append(f"{workload_label} containers[{index}] must be an object")
            continue
        image = container.get("image")
        if isinstance(image, str) and image.endswith(f"@{digest}"):
            regular_primary_matches += 1
    if regular_primary_matches == 0:
        errors.append(f"{workload_label} has no regular container bound to contract image_digest")

    for field in ("initContainers", "containers"):
        items = pod_spec.get(field, [])
        if items is None:
            items = []
        if not isinstance(items, list):
            errors.append(f"{workload_label} {field} must be a list")
            continue
        for index, container in enumerate(items):
            if not isinstance(container, dict):
                continue
            label = f"{workload_label} {field}[{index}]"
            security = container.get("securityContext")
            if not isinstance(security, dict):
                errors.append(f"{label} securityContext must be an object")
                continue
            capabilities = security.get("capabilities")
            additions = capabilities.get("add") if isinstance(capabilities, dict) else None
            if additions is not None:
                if not isinstance(additions, list):
                    errors.append(f"{label} capabilities.add must be a list when present")
                else:
                    for capability in additions:
                        if capability not in ALLOWED_ADDED_CAPABILITIES:
                            errors.append(f"{label} capabilities.add contains disallowed capability {capability!r}")
            if security.get("runAsUser") == 0:
                errors.append(f"{label} runAsUser must not be 0")
            errors.extend(_seccomp_errors(security.get("seccompProfile"), label))
    return errors


def _row_errors(key: str, row: dict[str, Any]) -> list[str]:
    path = _repo_file(row.get("manifest_path"))
    if path is None:
        return ["manifest_path must reference an existing repository file"]
    if path.suffix.lower() != ".json":
        return ["Kubernetes security hardening qualification requires rendered JSON manifest"]
    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        return ["contract row lacks a valid immutable image digest"]
    try:
        payload = _load(path)
    except Exception as exc:
        return [f"rendered JSON manifest is unreadable or invalid ({type(exc).__name__})"]
    docs, errors = _documents(payload)
    workload_count = 0
    for index, obj in enumerate(docs):
        if obj.get("kind") not in WORKLOAD_KINDS:
            continue
        workload_count += 1
        pod_spec = _pod_spec(obj)
        if pod_spec is None:
            errors.append(f"workload object {index} has no supported PodSpec")
            continue
        errors.extend(_pod_security_errors(pod_spec, digest, f"workload object {index}"))
    if workload_count == 0:
        errors.append("runtime manifest must contain at least one supported workload controller")
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    failures = _policy_errors(policy, source_policy)
    if failures:
        return failures

    key = "__security_hardening_self_test__"
    directory = TARGET / "manifests" / key
    directory.mkdir(parents=True, exist_ok=False)
    digest = "sha256:" + ("1" * 64)
    other_digest = "sha256:" + ("2" * 64)
    manifest_path = directory / "workload.json"
    row = {
        "manifest_path": manifest_path.relative_to(ROOT).as_posix(),
        "image_digest": digest,
    }

    def container(image_digest: str = digest) -> dict[str, Any]:
        return {
            "name": "runtime",
            "image": f"registry.example.invalid/runtime@{image_digest}",
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "runAsNonRoot": True,
                "runAsUser": 1000,
                "capabilities": {"drop": ["ALL"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "resources": {
                "requests": {"cpu": "500m", "memory": "512Mi"},
                "limits": {"cpu": "1", "memory": "1Gi"},
            },
        }

    def base_manifest() -> dict[str, Any]:
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "security-hardening-self-test"},
            "spec": {
                "selector": {"matchLabels": {"app": "runtime"}},
                "template": {
                    "metadata": {"labels": {"app": "runtime"}},
                    "spec": {
                        "securityContext": {
                            "runAsNonRoot": True,
                            "runAsUser": 1000,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [container()],
                    },
                },
            },
        }

    try:
        manifest = base_manifest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        valid_errors = _row_errors(key, row)
        if valid_errors:
            failures.append(f"valid synthetic hardened manifest was rejected: {valid_errors}")

        allowed = base_manifest()
        allowed["spec"]["template"]["spec"]["containers"][0]["securityContext"]["capabilities"]["add"] = ["NET_BIND_SERVICE"]
        manifest_path.write_text(json.dumps(allowed), encoding="utf-8")
        if _row_errors(key, row):
            failures.append("self-test rejected the sole Restricted-compatible added capability")

        localhost_ok = base_manifest()
        localhost_ok["spec"]["template"]["spec"]["securityContext"]["seccompProfile"] = {
            "type": "Localhost",
            "localhostProfile": "profiles/runtime.json",
        }
        manifest_path.write_text(json.dumps(localhost_ok), encoding="utf-8")
        if _row_errors(key, row):
            failures.append("self-test rejected valid Localhost seccomp profile structure")

        cases: list[tuple[str, dict[str, Any]]] = []
        bad = base_manifest()
        pod = bad["spec"]["template"]["spec"]
        pod["initContainers"] = [container()]
        pod["containers"] = [container(other_digest)]
        cases.append(("initContainer-only contract digest substitution", bad))

        bad = base_manifest()
        bad["spec"]["template"]["spec"]["containers"][0]["securityContext"]["capabilities"]["add"] = ["SYS_ADMIN"]
        cases.append(("disallowed capability re-add", bad))

        bad = base_manifest()
        bad["spec"]["template"]["spec"]["securityContext"]["runAsUser"] = 0
        cases.append(("pod runAsUser zero", bad))

        bad = base_manifest()
        bad["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsUser"] = 0
        cases.append(("container runAsUser zero", bad))

        bad = base_manifest()
        bad["spec"]["template"]["spec"]["securityContext"]["seccompProfile"] = {"type": "Localhost"}
        cases.append(("Localhost seccomp without localhostProfile", bad))

        bad = base_manifest()
        bad["spec"]["template"]["spec"]["securityContext"]["seccompProfile"] = {
            "type": "RuntimeDefault",
            "localhostProfile": "profiles/should-not-exist.json",
        }
        cases.append(("RuntimeDefault seccomp with localhostProfile", bad))

        for label, candidate in cases:
            manifest_path.write_text(json.dumps(candidate), encoding="utf-8")
            if not _row_errors(key, row):
                failures.append(f"self-test failed to reject {label}")
        return failures
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            (TARGET / "manifests").rmdir()
        except OSError:
            pass


def _contract_errors() -> tuple[list[str], tuple[int, int]]:
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    errors = _policy_errors(policy, source_policy)
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        return errors + ["runtime contract is not anchored to the sealed release"], (0, 0)
    defaults = contract.get("defaults_for_unresolved_fields", {})
    runtimes = contract.get("runtimes")
    if not isinstance(runtimes, list):
        return errors + ["runtime contract runtimes must be a list"], (0, 0)
    resolved = 0
    unresolved = 0
    for row in runtimes:
        if not isinstance(row, dict):
            errors.append("runtime contract contains a non-object row")
            continue
        key = str(row.get("key", "unknown"))
        ref = row.get("manifest_path", defaults.get("manifest_path"))
        if ref in (None, "", [], {}):
            unresolved += 1
            continue
        row_errors = _row_errors(key, row)
        if row_errors:
            errors.extend(f"{key}: {item}" for item in row_errors)
        else:
            resolved += 1
    return errors, (resolved, unresolved)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed security hardening validator for rendered Kubernetes runtime manifests."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--contract", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        failures = _self_test()
        if failures:
            for failure in failures:
                print(f"SELF-TEST FAILURE: {failure}")
            return 4
        print(
            "PASS: Kubernetes manifest security hardening rejects initContainer-only digest binding, "
            "disallowed capability re-addition, runAsUser=0, and malformed Localhost seccomp profiles"
        )
        return 0

    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"KUBERNETES MANIFEST SECURITY BLOCKER: {error}")
        return 2
    resolved, unresolved = counts
    print(
        f"PASS: kubernetes_manifest_security_hardening: validated {resolved} resolved manifests; "
        f"{unresolved} remain unresolved"
    )
    print(
        "BOUNDARY: static Kubernetes manifest security evidence only; it does not prove API admission, "
        "scheduler placement, runtime health, network reachability, deployment, production authorization, "
        "or independent validation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
