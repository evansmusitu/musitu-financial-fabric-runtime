from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
SOURCE_POLICY = TARGET / "manifest-profile-policy.json"
POLICY = TARGET / "kubernetes-manifest-semantics-policy.json"

EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.kubernetes-manifest-semantics-policy.v1"
SOURCE_POLICY_SCHEMA = "mff.manifest-profile-policy.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
PINNED_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob")
REQUIRED_RESOURCES = ("cpu", "memory")
FORBIDDEN_POD_FLAGS = ("hostNetwork", "hostPID", "hostIPC")
FORBIDDEN_VOLUME_TYPES = ("hostPath",)
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
    errors: list[str] = []
    if not isinstance(policy, dict):
        return ["Kubernetes manifest semantics policy root must be an object"]
    expected = {
        "schema_version": POLICY_SCHEMA,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "source_manifest_policy_schema_version": SOURCE_POLICY_SCHEMA,
        "qualified_manifest_format": "json",
        "required_namespace": "musitu-financial-fabric-target-staging",
        "required_part_of_label": {
            "key": "app.kubernetes.io/part-of",
            "value": "musitu-financial-fabric",
        },
        "required_runtime_label_key": "app.kubernetes.io/name",
        "allowed_workload_kinds": list(WORKLOAD_KINDS),
        "required_compute_resources": list(REQUIRED_RESOURCES),
        "required_container_security": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities_drop_all": True,
        },
        "required_non_root": True,
        "allowed_seccomp_types": list(ALLOWED_SECCOMP),
        "forbidden_pod_flags": list(FORBIDDEN_POD_FLAGS),
        "forbidden_volume_types": list(FORBIDDEN_VOLUME_TYPES),
    }
    for field, value in expected.items():
        if policy.get(field) != value:
            errors.append(f"Kubernetes manifest semantics policy {field} is invalid")

    if not isinstance(source_policy, dict):
        return errors + ["source manifest policy root must be an object"]
    if source_policy.get("schema_version") != SOURCE_POLICY_SCHEMA:
        errors.append("source manifest policy schema drifted")
    if source_policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("source manifest policy is not anchored to the sealed runtime release")
    if source_policy.get("required_namespace") != policy.get("required_namespace"):
        errors.append("semantic namespace does not match source manifest policy")
    allowed = set(source_policy.get("allowed_manifest_extensions") or [])
    if ".json" not in allowed:
        errors.append("source manifest policy no longer permits rendered JSON")
    if source_policy.get("rendered_output_required") is not True:
        errors.append("source manifest policy no longer requires rendered output")
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
            if not isinstance(item, dict):
                errors.append(f"Kubernetes List item {index} must be an object")
            else:
                docs.append(item)
        return docs, errors
    return [payload], []


def _metadata_errors(key: str, index: int, obj: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj.get("apiVersion"), str) or not obj["apiVersion"].strip():
        errors.append(f"object {index} apiVersion is missing")
    if not isinstance(obj.get("kind"), str) or not obj["kind"].strip():
        errors.append(f"object {index} kind is missing")
    metadata = obj.get("metadata")
    if not isinstance(metadata, dict):
        return errors + [f"object {index} metadata must be an object"]
    if not isinstance(metadata.get("name"), str) or not metadata["name"].strip():
        errors.append(f"object {index} metadata.name is missing")
    if metadata.get("namespace") != policy.get("required_namespace"):
        errors.append(f"object {index} namespace does not match required staging namespace")
    labels = metadata.get("labels")
    if not isinstance(labels, dict):
        return errors + [f"object {index} metadata.labels must be an object"]
    part = policy["required_part_of_label"]
    if labels.get(part["key"]) != part["value"]:
        errors.append(f"object {index} part-of label is missing or invalid")
    if labels.get(policy["required_runtime_label_key"]) != key:
        errors.append(f"object {index} runtime label does not match contract runtime")
    return errors


def _pod_spec(obj: dict[str, Any]) -> dict[str, Any] | None:
    kind = obj.get("kind")
    spec = obj.get("spec")
    if not isinstance(spec, dict):
        return None
    if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job"}:
        template = spec.get("template")
        if isinstance(template, dict) and isinstance(template.get("spec"), dict):
            return template["spec"]
        return None
    if kind == "CronJob":
        job_template = spec.get("jobTemplate")
        if not isinstance(job_template, dict):
            return None
        job_spec = job_template.get("spec")
        if not isinstance(job_spec, dict):
            return None
        template = job_spec.get("template")
        if isinstance(template, dict) and isinstance(template.get("spec"), dict):
            return template["spec"]
    return None


def _resource_profile(row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    path = _repo_file(row.get("resource_profile"))
    if path is None:
        return None, ["resource_profile must reference an existing repository JSON file"]
    try:
        payload = _load(path)
    except Exception as exc:
        return None, [f"resource_profile is unreadable or invalid JSON ({type(exc).__name__})"]
    if not isinstance(payload, dict):
        return None, ["resource_profile root must be an object"]
    return payload, []


def _container_errors(
    pod_spec: dict[str, Any],
    digest: str,
    resource_profile: dict[str, Any],
    workload_label: str,
) -> tuple[list[str], int]:
    errors: list[str] = []
    primary_matches = 0
    pod_security = pod_spec.get("securityContext")
    pod_security = pod_security if isinstance(pod_security, dict) else {}
    pod_non_root = pod_security.get("runAsNonRoot") is True
    pod_seccomp = pod_security.get("seccompProfile")
    pod_seccomp_type = pod_seccomp.get("type") if isinstance(pod_seccomp, dict) else None

    for flag in FORBIDDEN_POD_FLAGS:
        if pod_spec.get(flag) is True:
            errors.append(f"{workload_label} sets forbidden {flag}=true")

    volumes = pod_spec.get("volumes", [])
    if volumes is not None and not isinstance(volumes, list):
        errors.append(f"{workload_label} volumes must be a list")
    elif isinstance(volumes, list):
        for index, volume in enumerate(volumes):
            if not isinstance(volume, dict):
                errors.append(f"{workload_label} volume {index} must be an object")
                continue
            for forbidden in FORBIDDEN_VOLUME_TYPES:
                if forbidden in volume:
                    errors.append(f"{workload_label} volume {index} uses forbidden {forbidden}")

    all_containers: list[tuple[str, int, dict[str, Any]]] = []
    for field in ("initContainers", "containers"):
        items = pod_spec.get(field, [])
        if field == "containers" and (not isinstance(items, list) or not items):
            errors.append(f"{workload_label} must contain at least one container")
            continue
        if items is None:
            items = []
        if not isinstance(items, list):
            errors.append(f"{workload_label} {field} must be a list")
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{workload_label} {field}[{index}] must be an object")
            else:
                all_containers.append((field, index, item))

    for field, index, container in all_containers:
        label = f"{workload_label} {field}[{index}]"
        image = container.get("image")
        if not isinstance(image, str) or not PINNED_IMAGE.fullmatch(image):
            errors.append(f"{label} image must be immutable repository@sha256")
            is_primary = False
        else:
            is_primary = image.endswith(f"@{digest}")
            if is_primary:
                primary_matches += 1

        security = container.get("securityContext")
        if not isinstance(security, dict):
            errors.append(f"{label} securityContext must be an object")
            security = {}
        if security.get("privileged") is True:
            errors.append(f"{label} must not be privileged")
        if security.get("allowPrivilegeEscalation") is not False:
            errors.append(f"{label} allowPrivilegeEscalation must be false")
        if security.get("readOnlyRootFilesystem") is not True:
            errors.append(f"{label} readOnlyRootFilesystem must be true")
        caps = security.get("capabilities")
        drops = caps.get("drop") if isinstance(caps, dict) else None
        if not isinstance(drops, list) or "ALL" not in drops:
            errors.append(f"{label} capabilities.drop must include ALL")
        if not pod_non_root and security.get("runAsNonRoot") is not True:
            errors.append(f"{label} must inherit or set runAsNonRoot=true")
        container_seccomp = security.get("seccompProfile")
        container_seccomp_type = (
            container_seccomp.get("type") if isinstance(container_seccomp, dict) else None
        )
        effective_seccomp = container_seccomp_type or pod_seccomp_type
        if effective_seccomp not in ALLOWED_SECCOMP:
            errors.append(f"{label} must inherit or set an allowed seccomp profile")

        resources = container.get("resources")
        if not isinstance(resources, dict):
            errors.append(f"{label} resources must be an object")
            continue
        for block_name in ("requests", "limits"):
            block = resources.get(block_name)
            if not isinstance(block, dict):
                errors.append(f"{label} resources.{block_name} must be an object")
                continue
            for resource in REQUIRED_RESOURCES:
                if not isinstance(block.get(resource), str) or not block[resource].strip():
                    errors.append(f"{label} resources.{block_name}.{resource} is missing")

        if is_primary:
            for block_name in ("requests", "limits"):
                expected_block = resource_profile.get(block_name)
                actual_block = resources.get(block_name) if isinstance(resources, dict) else None
                if not isinstance(expected_block, dict) or not isinstance(actual_block, dict):
                    errors.append(f"{label} cannot compare {block_name} with resource profile")
                    continue
                for resource in REQUIRED_RESOURCES:
                    if actual_block.get(resource) != expected_block.get(resource):
                        errors.append(
                            f"{label} resources.{block_name}.{resource} does not match resource_profile"
                        )
    return errors, primary_matches


def _row_errors(key: str, row: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    path = _repo_file(row.get("manifest_path"))
    if path is None:
        return ["manifest_path must reference an existing repository file"]
    if path.suffix.lower() != ".json":
        return ["canonical Kubernetes semantic qualification requires rendered JSON manifest"]

    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks a valid immutable image digest")

    resource_profile, resource_errors = _resource_profile(row)
    errors.extend(resource_errors)
    if resource_profile is None:
        return errors
    if resource_profile.get("runtime_key") != key:
        errors.append("resource_profile runtime_key does not match contract row")
    if resource_profile.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("resource_profile is not bound to the sealed runtime release")
    if resource_profile.get("image_digest") != digest:
        errors.append("resource_profile image_digest does not match contract row")

    try:
        payload = _load(path)
    except Exception as exc:
        return errors + [f"rendered JSON manifest is unreadable or invalid ({type(exc).__name__})"]
    docs, doc_errors = _documents(payload)
    errors.extend(doc_errors)
    if not docs:
        return errors

    workload_count = 0
    primary_matches = 0
    for index, obj in enumerate(docs):
        errors.extend(_metadata_errors(key, index, obj, policy))
        if obj.get("kind") not in WORKLOAD_KINDS:
            continue
        workload_count += 1
        pod_spec = _pod_spec(obj)
        if pod_spec is None:
            errors.append(f"workload object {index} has no supported PodSpec")
            continue
        container_errors, matches = _container_errors(
            pod_spec, str(digest), resource_profile, f"workload object {index}"
        )
        errors.extend(container_errors)
        primary_matches += matches

    if workload_count == 0:
        errors.append("runtime manifest must contain at least one supported workload controller")
    if primary_matches == 0:
        errors.append("runtime manifest has no primary container bound to contract image_digest")
    return errors


def _self_test() -> list[str]:
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    failures = _policy_errors(policy, source_policy)
    if failures:
        return failures

    key = "__semantic_self_test__"
    directory = TARGET / "manifests" / key
    directory.mkdir(parents=True, exist_ok=False)
    digest = "sha256:" + ("1" * 64)
    profile_path = directory / "resource-profile.json"
    manifest_path = directory / "workload.json"
    yaml_path = directory / "workload.yaml"
    resource_profile = {
        "runtime_key": key,
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "requests": {"cpu": "500m", "memory": "512Mi"},
        "limits": {"cpu": "1", "memory": "1Gi"},
    }
    profile_path.write_text(json.dumps(resource_profile), encoding="utf-8")

    def base_manifest() -> dict[str, Any]:
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "semantic-self-test",
                "namespace": policy["required_namespace"],
                "labels": {
                    "app.kubernetes.io/part-of": "musitu-financial-fabric",
                    "app.kubernetes.io/name": key,
                },
            },
            "spec": {
                "selector": {"matchLabels": {"app.kubernetes.io/name": key}},
                "template": {
                    "metadata": {"labels": {"app.kubernetes.io/name": key}},
                    "spec": {
                        "securityContext": {
                            "runAsNonRoot": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "containers": [
                            {
                                "name": key,
                                "image": f"registry.example.invalid/{key}@{digest}",
                                "securityContext": {
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "resources": {
                                    "requests": resource_profile["requests"],
                                    "limits": resource_profile["limits"],
                                },
                            }
                        ],
                    },
                },
            },
        }

    row = {
        "manifest_path": manifest_path.relative_to(ROOT).as_posix(),
        "image_digest": digest,
        "resource_profile": profile_path.relative_to(ROOT).as_posix(),
    }

    try:
        manifest = base_manifest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        valid_errors = _row_errors(key, row, policy)
        if valid_errors:
            failures.append(f"valid synthetic Kubernetes manifest was rejected: {valid_errors}")

        yaml_path.write_text("apiVersion: apps/v1\nkind: Deployment\n", encoding="utf-8")
        changed = dict(row)
        changed["manifest_path"] = yaml_path.relative_to(ROOT).as_posix()
        if not _row_errors(key, changed, policy):
            failures.append("self-test failed to reject YAML as canonical semantic qualification input")

        cases: list[tuple[str, Any]] = []
        bad = base_manifest()
        bad["kind"] = "ConfigMap"
        cases.append(("non-workload manifest", bad))
        bad = base_manifest()
        bad["metadata"]["namespace"] = "wrong"
        cases.append(("namespace drift", bad))
        bad = base_manifest()
        bad["metadata"]["labels"]["app.kubernetes.io/name"] = "wrong"
        cases.append(("runtime label drift", bad))
        bad = base_manifest()
        bad["spec"]["template"]["spec"]["containers"][0]["image"] = "registry.example.invalid/test:latest"
        cases.append(("mutable image", bad))
        bad = base_manifest()
        bad["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"] = "2Gi"
        cases.append(("resource profile drift", bad))
        bad = base_manifest()
        bad["spec"]["template"]["spec"]["containers"][0]["securityContext"]["allowPrivilegeEscalation"] = True
        cases.append(("privilege escalation", bad))
        bad = base_manifest()
        bad["spec"]["template"]["spec"]["volumes"] = [{"name": "host", "hostPath": {"path": "/"}}]
        cases.append(("hostPath volume", bad))
        bad = base_manifest()
        bad["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] = False
        cases.append(("non-root drift", bad))
        for label, candidate in cases:
            manifest_path.write_text(json.dumps(candidate), encoding="utf-8")
            if not _row_errors(key, row, policy):
                failures.append(f"self-test failed to reject {label}")
        return failures
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        try:
            (TARGET / "manifests").rmdir()
        except OSError:
            pass


def _contract_errors() -> tuple[list[str], tuple[int, int]]:
    errors: list[str] = []
    policy = _load(POLICY)
    source_policy = _load(SOURCE_POLICY)
    errors.extend(_policy_errors(policy, source_policy))
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors, (0, 0)

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
        row_errors = _row_errors(key, row, policy)
        if row_errors:
            errors.extend(f"{key}: {item}" for item in row_errors)
        else:
            resolved += 1
    return errors, (resolved, unresolved)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed semantic validator for rendered Kubernetes runtime manifests."
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
            "PASS: Kubernetes manifest semantic validator rejects non-workload/unbound manifests, "
            "YAML-only semantic ambiguity, namespace/runtime/image/resource drift, privileged pod "
            "semantics, hostPath, and non-root drift"
        )
        return 0

    errors, counts = _contract_errors()
    if errors:
        for error in errors:
            print(f"KUBERNETES MANIFEST SEMANTIC BLOCKER: {error}")
        return 2
    resolved, unresolved = counts
    print(
        f"PASS: kubernetes_manifest_semantics: validated {resolved} resolved manifests; "
        f"{unresolved} remain unresolved"
    )
    print(
        "BOUNDARY: parsed rendered JSON semantics are static evidence only; they do not prove "
        "Kubernetes API admission, scheduler placement, runtime health, network reachability, "
        "deployment, production authorization, or independent validation"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
