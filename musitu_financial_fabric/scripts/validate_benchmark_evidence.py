from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
CONTRACT = TARGET / "runtime-contract.json"
POLICY = TARGET / "benchmark-evidence-policy.json"
PLAN = TARGET / "resource-benchmark-plan.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
EVIDENCE_SCHEMA = "mff.runtime-benchmark-evidence.v1"
POLICY_SCHEMA = "mff.benchmark-evidence-policy.v2"
PLAN_SCHEMA = "mff.resource-benchmark-plan.v1"
SEMANTIC_PROFILE = "mff.benchmark-semantic-profile.v1"
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_BINDINGS = (
    "runtime_key",
    "authoritative_runtime_base_commit",
    "image_digest",
    "manifest_path",
    "resource_profile",
    "environment_id",
    "executed_at",
    "measurement_toolchain",
    "raw_evidence_ref",
    "raw_evidence_sha256",
)
PLAN_EVIDENCE_BINDINGS = tuple(field for field in REQUIRED_BINDINGS if field != "raw_evidence_ref")
REQUIRED_LOAD_MODEL = (
    "request_or_message_rate",
    "concurrency",
    "payload_size_distribution",
    "read_write_mix",
    "dataset_or_state_size",
    "test_duration",
    "failure_or_restart_scenario",
)
REQUIRED_MEASUREMENTS = (
    "cpu_p50",
    "cpu_p95",
    "memory_rss_p50",
    "memory_rss_p95",
    "latency_p50",
    "latency_p95",
    "latency_p99",
    "error_rate",
    "restart_recovery_time",
    "queue_or_backlog_depth_where_applicable",
    "storage_iops_and_latency_where_applicable",
)
CANONICAL_UNITS = {
    "request_or_message_rate": "per_second",
    "concurrency": "in_flight",
    "payload_size": "bytes",
    "dataset_or_state_size": "bytes",
    "test_duration": "seconds",
    "cpu": "cores",
    "memory_rss": "bytes",
    "latency": "milliseconds",
    "error_rate": "ratio",
    "restart_recovery_time": "seconds",
    "queue_or_backlog_depth": "items",
    "storage_iops": "operations_per_second",
    "storage_latency": "milliseconds",
}
SEMANTIC_RULES = {
    "positive_rate": True,
    "positive_concurrency": True,
    "positive_test_duration": True,
    "failure_or_restart_scenario_must_be_performed": True,
    "percentile_ordering_required": True,
    "percentile_sample_counts_must_match_within_series": True,
    "error_rate_ratio_min": 0,
    "error_rate_ratio_max": 1,
    "applicability_statuses": ["measured", "not_applicable"],
    "not_applicable_requires_rationale": True,
}


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


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _decimal_number(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _integer(value: object, *, minimum: int = 0) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return None
    return value


def _scalar_metric_errors(
    payload: object,
    *,
    label: str,
    unit: str,
    minimum: Decimal = Decimal(0),
    positive: bool = False,
    sample_count: bool = False,
) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    value = _decimal_number(payload.get("value"))
    if value is None:
        errors.append(f"{label}.value must be a finite JSON number")
    elif positive and value <= 0:
        errors.append(f"{label}.value must be greater than zero")
    elif not positive and value < minimum:
        errors.append(f"{label}.value must be at least {minimum}")
    if payload.get("unit") != unit:
        errors.append(f"{label}.unit must be {unit}")
    if sample_count and _integer(payload.get("sample_count"), minimum=1) is None:
        errors.append(f"{label}.sample_count must be a positive integer")
    return errors


def _applicability_errors(payload: object, *, label: str) -> tuple[list[str], str | None]:
    if not isinstance(payload, dict):
        return [f"{label} must be an object"], None
    status = payload.get("status")
    if status not in ("measured", "not_applicable"):
        return [f"{label}.status must be measured or not_applicable"], None
    if status == "not_applicable" and not _nonempty_string(payload.get("rationale")):
        return [f"{label}.rationale is required when status=not_applicable"], status
    return [], str(status)


def _policy_errors() -> list[str]:
    errors: list[str] = []
    try:
        policy = _load(POLICY)
    except Exception as exc:
        return [f"benchmark policy unavailable or invalid JSON: {type(exc).__name__}"]
    if not isinstance(policy, dict):
        return ["benchmark policy root must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("benchmark policy schema version is invalid")
    if policy.get("benchmark_evidence_schema_version") != EVIDENCE_SCHEMA:
        errors.append("benchmark evidence schema version does not match policy")
    if policy.get("benchmark_semantic_profile_version") != SEMANTIC_PROFILE:
        errors.append("benchmark semantic profile version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("benchmark policy is not bound to the sealed runtime release")
    if policy.get("required_bindings") != list(REQUIRED_BINDINGS):
        errors.append("benchmark policy required bindings do not exactly match validator policy")
    if policy.get("canonical_units") != CANONICAL_UNITS:
        errors.append("benchmark policy canonical units do not exactly match validator policy")
    if policy.get("semantic_rules") != SEMANTIC_RULES:
        errors.append("benchmark policy semantic rules do not exactly match validator policy")
    raw_rule = policy.get("raw_evidence_rule")
    if not _nonempty_string(raw_rule):
        errors.append("benchmark policy raw_evidence_rule is missing")
    return errors


def _plan_errors() -> list[str]:
    errors: list[str] = []
    try:
        plan = _load(PLAN)
    except Exception as exc:
        return [f"benchmark plan unavailable or invalid JSON: {type(exc).__name__}"]
    if not isinstance(plan, dict):
        return ["benchmark plan root must be an object"]
    if plan.get("schema_version") != PLAN_SCHEMA:
        errors.append("benchmark plan schema version is invalid")
    if plan.get("benchmark_status_required_for_deployability") != "measured":
        errors.append("benchmark plan does not require measured status")
    if plan.get("benchmark_evidence_schema_version") != EVIDENCE_SCHEMA:
        errors.append("benchmark plan evidence schema version is invalid")
    if plan.get("benchmark_semantic_profile_version") != SEMANTIC_PROFILE:
        errors.append("benchmark plan semantic profile version is invalid")
    if plan.get("required_load_model") != list(REQUIRED_LOAD_MODEL):
        errors.append("benchmark plan load-model requirements do not exactly match validator policy")
    if plan.get("required_measurements") != list(REQUIRED_MEASUREMENTS):
        errors.append("benchmark plan measurement requirements do not exactly match validator policy")
    if plan.get("required_evidence_bindings") != list(PLAN_EVIDENCE_BINDINGS):
        errors.append("benchmark plan evidence bindings do not exactly match validator policy")
    if not _nonempty_string(plan.get("semantic_acceptance_rule")):
        errors.append("benchmark plan semantic_acceptance_rule is missing")
    return errors


def _load_model_errors(load_model: object) -> tuple[list[str], int | None]:
    if not isinstance(load_model, dict):
        return ["load_model must be an object"], None
    errors: list[str] = []
    for field in REQUIRED_LOAD_MODEL:
        if field not in load_model:
            errors.append(f"load_model missing {field}")

    errors.extend(
        _scalar_metric_errors(
            load_model.get("request_or_message_rate"),
            label="load_model.request_or_message_rate",
            unit=CANONICAL_UNITS["request_or_message_rate"],
            positive=True,
        )
    )
    errors.extend(
        _scalar_metric_errors(
            load_model.get("concurrency"),
            label="load_model.concurrency",
            unit=CANONICAL_UNITS["concurrency"],
            positive=True,
        )
    )
    concurrency = load_model.get("concurrency")
    if isinstance(concurrency, dict) and _integer(concurrency.get("value"), minimum=1) is None:
        errors.append("load_model.concurrency.value must be a positive integer")

    payload = load_model.get("payload_size_distribution")
    if not isinstance(payload, dict):
        errors.append("load_model.payload_size_distribution must be an object")
    else:
        if payload.get("unit") != CANONICAL_UNITS["payload_size"]:
            errors.append("load_model.payload_size_distribution.unit must be bytes")
        values: dict[str, int] = {}
        for name in ("p50", "p95", "p99"):
            parsed = _integer(payload.get(name), minimum=0)
            if parsed is None:
                errors.append(f"load_model.payload_size_distribution.{name} must be a non-negative integer")
            else:
                values[name] = parsed
        if len(values) == 3 and not (values["p50"] <= values["p95"] <= values["p99"]):
            errors.append("load_model payload-size percentiles must satisfy p50 <= p95 <= p99")

    read_write = load_model.get("read_write_mix")
    applicability, status = _applicability_errors(read_write, label="load_model.read_write_mix")
    errors.extend(applicability)
    if status == "measured" and isinstance(read_write, dict):
        read_ratio = _decimal_number(read_write.get("read_ratio"))
        write_ratio = _decimal_number(read_write.get("write_ratio"))
        for name, value in (("read_ratio", read_ratio), ("write_ratio", write_ratio)):
            if value is None or value < 0 or value > 1:
                errors.append(f"load_model.read_write_mix.{name} must be a ratio from 0 to 1")
        if read_ratio is not None and write_ratio is not None and read_ratio + write_ratio != Decimal(1):
            errors.append("load_model.read_write_mix read_ratio + write_ratio must equal 1")

    dataset = load_model.get("dataset_or_state_size")
    applicability, status = _applicability_errors(dataset, label="load_model.dataset_or_state_size")
    errors.extend(applicability)
    if status == "measured" and isinstance(dataset, dict):
        if dataset.get("unit") != CANONICAL_UNITS["dataset_or_state_size"]:
            errors.append("load_model.dataset_or_state_size.unit must be bytes")
        if _integer(dataset.get("value"), minimum=0) is None:
            errors.append("load_model.dataset_or_state_size.value must be a non-negative integer")

    errors.extend(
        _scalar_metric_errors(
            load_model.get("test_duration"),
            label="load_model.test_duration",
            unit=CANONICAL_UNITS["test_duration"],
            positive=True,
        )
    )

    failure = load_model.get("failure_or_restart_scenario")
    failure_iterations: int | None = None
    if not isinstance(failure, dict):
        errors.append("load_model.failure_or_restart_scenario must be an object")
    else:
        if failure.get("performed") is not True:
            errors.append("load_model.failure_or_restart_scenario.performed must be true")
        if not _nonempty_string(failure.get("description")):
            errors.append("load_model.failure_or_restart_scenario.description is missing")
        failure_iterations = _integer(failure.get("iterations"), minimum=1)
        if failure_iterations is None:
            errors.append("load_model.failure_or_restart_scenario.iterations must be a positive integer")
    return errors, failure_iterations


def _measurement_errors(measurements: object, *, failure_iterations: int | None) -> list[str]:
    if not isinstance(measurements, dict):
        return ["measurements must be an object"]
    errors: list[str] = []
    for field in REQUIRED_MEASUREMENTS:
        if field not in measurements:
            errors.append(f"measurements missing {field}")

    series = {
        "cpu": (("cpu_p50", "cpu_p95"), CANONICAL_UNITS["cpu"]),
        "memory_rss": (("memory_rss_p50", "memory_rss_p95"), CANONICAL_UNITS["memory_rss"]),
        "latency": (("latency_p50", "latency_p95", "latency_p99"), CANONICAL_UNITS["latency"]),
    }
    parsed_series: dict[str, dict[str, Decimal]] = {}
    samples: dict[str, list[int]] = {}
    for series_name, (fields, unit) in series.items():
        parsed_series[series_name] = {}
        samples[series_name] = []
        for field in fields:
            metric = measurements.get(field)
            errors.extend(
                _scalar_metric_errors(
                    metric,
                    label=f"measurements.{field}",
                    unit=unit,
                    minimum=Decimal(0),
                    sample_count=True,
                )
            )
            if isinstance(metric, dict):
                value = _decimal_number(metric.get("value"))
                if value is not None and value >= 0:
                    parsed_series[series_name][field] = value
                sample = _integer(metric.get("sample_count"), minimum=1)
                if sample is not None:
                    samples[series_name].append(sample)

    cpu = parsed_series["cpu"]
    if len(cpu) == 2 and cpu["cpu_p50"] > cpu["cpu_p95"]:
        errors.append("CPU percentiles must satisfy p50 <= p95")
    memory = parsed_series["memory_rss"]
    if len(memory) == 2 and memory["memory_rss_p50"] > memory["memory_rss_p95"]:
        errors.append("memory RSS percentiles must satisfy p50 <= p95")
    latency = parsed_series["latency"]
    if len(latency) == 3 and not (
        latency["latency_p50"] <= latency["latency_p95"] <= latency["latency_p99"]
    ):
        errors.append("latency percentiles must satisfy p50 <= p95 <= p99")
    for series_name, counts in samples.items():
        if len(counts) > 1 and len(set(counts)) != 1:
            errors.append(f"{series_name} percentile sample_count values must match")

    error_rate = measurements.get("error_rate")
    if not isinstance(error_rate, dict):
        errors.append("measurements.error_rate must be an object")
    else:
        value = _decimal_number(error_rate.get("value"))
        if value is None or value < 0 or value > 1:
            errors.append("measurements.error_rate.value must be a ratio from 0 to 1")
        if error_rate.get("unit") != CANONICAL_UNITS["error_rate"]:
            errors.append("measurements.error_rate.unit must be ratio")
        errors_count = _integer(error_rate.get("errors"), minimum=0)
        total_count = _integer(error_rate.get("total"), minimum=1)
        if errors_count is None:
            errors.append("measurements.error_rate.errors must be a non-negative integer")
        if total_count is None:
            errors.append("measurements.error_rate.total must be a positive integer")
        if errors_count is not None and total_count is not None:
            if errors_count > total_count:
                errors.append("measurements.error_rate.errors must not exceed total")
            elif value is not None:
                expected = Decimal(errors_count) / Decimal(total_count)
                if abs(value - expected) > Decimal("1e-9"):
                    errors.append("measurements.error_rate.value does not match errors / total")

    restart = measurements.get("restart_recovery_time")
    errors.extend(
        _scalar_metric_errors(
            restart,
            label="measurements.restart_recovery_time",
            unit=CANONICAL_UNITS["restart_recovery_time"],
            minimum=Decimal(0),
        )
    )
    if isinstance(restart, dict):
        iterations = _integer(restart.get("iterations"), minimum=1)
        if iterations is None:
            errors.append("measurements.restart_recovery_time.iterations must be a positive integer")
        elif failure_iterations is not None and iterations != failure_iterations:
            errors.append("restart recovery iterations must match failure/restart scenario iterations")

    queue = measurements.get("queue_or_backlog_depth_where_applicable")
    applicability, status = _applicability_errors(
        queue, label="measurements.queue_or_backlog_depth_where_applicable"
    )
    errors.extend(applicability)
    if status == "measured" and isinstance(queue, dict):
        if queue.get("unit") != CANONICAL_UNITS["queue_or_backlog_depth"]:
            errors.append("queue/backlog unit must be items")
        if _integer(queue.get("value"), minimum=0) is None:
            errors.append("queue/backlog value must be a non-negative integer")
        if _integer(queue.get("sample_count"), minimum=1) is None:
            errors.append("queue/backlog sample_count must be a positive integer")

    storage = measurements.get("storage_iops_and_latency_where_applicable")
    applicability, status = _applicability_errors(
        storage, label="measurements.storage_iops_and_latency_where_applicable"
    )
    errors.extend(applicability)
    if status == "measured" and isinstance(storage, dict):
        errors.extend(
            _scalar_metric_errors(
                storage.get("iops"),
                label="measurements.storage_iops_and_latency_where_applicable.iops",
                unit=CANONICAL_UNITS["storage_iops"],
                minimum=Decimal(0),
                sample_count=True,
            )
        )
        errors.extend(
            _scalar_metric_errors(
                storage.get("latency_p95"),
                label="measurements.storage_iops_and_latency_where_applicable.latency_p95",
                unit=CANONICAL_UNITS["storage_latency"],
                minimum=Decimal(0),
                sample_count=True,
            )
        )
        iops = storage.get("iops")
        latency_p95 = storage.get("latency_p95")
        if isinstance(iops, dict) and isinstance(latency_p95, dict):
            iops_samples = _integer(iops.get("sample_count"), minimum=1)
            latency_samples = _integer(latency_p95.get("sample_count"), minimum=1)
            if (
                iops_samples is not None
                and latency_samples is not None
                and iops_samples != latency_samples
            ):
                errors.append("storage IOPS and latency sample_count values must match")
    return errors


def evidence_errors(key: str, row: dict[str, Any], payload: object) -> list[str]:
    errors = _policy_errors() + _plan_errors()
    if not isinstance(payload, dict):
        return errors + ["benchmark evidence root must be an object"]
    if payload.get("schema_version") != EVIDENCE_SCHEMA:
        errors.append("benchmark evidence schema version is invalid")
    if payload.get("runtime_key") != key:
        errors.append("runtime_key does not match contract row")
    if payload.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("evidence is not bound to the sealed runtime release")

    digest = row.get("image_digest")
    if not isinstance(digest, str) or not OCI_DIGEST.fullmatch(digest):
        errors.append("contract row lacks an immutable image digest")
    elif payload.get("image_digest") != digest:
        errors.append("image_digest does not match contract row")
    if payload.get("manifest_path") != row.get("manifest_path"):
        errors.append("manifest_path does not match contract row")
    if payload.get("resource_profile") != row.get("resource_profile"):
        errors.append("resource_profile does not match contract row")
    if not _nonempty_string(payload.get("environment_id")):
        errors.append("environment_id is missing")

    try:
        executed = datetime.fromisoformat(str(payload.get("executed_at", "")).replace("Z", "+00:00"))
        if executed.tzinfo is None:
            raise ValueError("timezone missing")
    except (TypeError, ValueError):
        errors.append("executed_at must be an offset-aware ISO-8601 timestamp")

    toolchain = payload.get("measurement_toolchain")
    if not isinstance(toolchain, dict):
        errors.append("measurement_toolchain must be an object")
    else:
        for field in ("driver", "version", "collector"):
            if not _nonempty_string(toolchain.get(field)):
                errors.append(f"measurement_toolchain.{field} is missing")

    raw_path = _repo_file(payload.get("raw_evidence_ref"))
    if raw_path is None:
        errors.append("raw_evidence_ref is not an existing repository-relative file")
    raw_sha = str(payload.get("raw_evidence_sha256", "")).strip().lower()
    if not SHA256_HEX.fullmatch(raw_sha):
        errors.append("raw_evidence_sha256 is missing or malformed")
    elif raw_path is not None:
        actual = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        if actual != raw_sha:
            errors.append("raw_evidence_sha256 does not match raw_evidence_ref bytes")

    load_errors, failure_iterations = _load_model_errors(payload.get("load_model"))
    errors.extend(load_errors)
    errors.extend(_measurement_errors(payload.get("measurements"), failure_iterations=failure_iterations))
    return errors


def _valid_synthetic_payload(raw_ref: str, raw_sha: str, digest: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "runtime_key": "self-test",
        "authoritative_runtime_base_commit": EXPECTED_BASE_COMMIT,
        "image_digest": digest,
        "manifest_path": row["manifest_path"],
        "resource_profile": row["resource_profile"],
        "environment_id": "self-test-target",
        "executed_at": "2026-09-12T00:00:00+00:00",
        "measurement_toolchain": {
            "driver": "validator-self-test",
            "version": "1",
            "collector": "synthetic",
        },
        "raw_evidence_ref": raw_ref,
        "raw_evidence_sha256": raw_sha,
        "load_model": {
            "request_or_message_rate": {"value": 100, "unit": "per_second"},
            "concurrency": {"value": 8, "unit": "in_flight"},
            "payload_size_distribution": {"unit": "bytes", "p50": 256, "p95": 1024, "p99": 4096},
            "read_write_mix": {"status": "measured", "read_ratio": 0.7, "write_ratio": 0.3},
            "dataset_or_state_size": {"status": "measured", "value": 1048576, "unit": "bytes"},
            "test_duration": {"value": 300, "unit": "seconds"},
            "failure_or_restart_scenario": {
                "performed": True,
                "description": "synthetic restart validation",
                "iterations": 3,
            },
        },
        "measurements": {
            "cpu_p50": {"value": 0.2, "unit": "cores", "sample_count": 1000},
            "cpu_p95": {"value": 0.7, "unit": "cores", "sample_count": 1000},
            "memory_rss_p50": {"value": 100000000, "unit": "bytes", "sample_count": 1000},
            "memory_rss_p95": {"value": 160000000, "unit": "bytes", "sample_count": 1000},
            "latency_p50": {"value": 5, "unit": "milliseconds", "sample_count": 1000},
            "latency_p95": {"value": 20, "unit": "milliseconds", "sample_count": 1000},
            "latency_p99": {"value": 40, "unit": "milliseconds", "sample_count": 1000},
            "error_rate": {"value": 0.01, "unit": "ratio", "errors": 10, "total": 1000},
            "restart_recovery_time": {"value": 2.5, "unit": "seconds", "iterations": 3},
            "queue_or_backlog_depth_where_applicable": {
                "status": "measured",
                "value": 4,
                "unit": "items",
                "sample_count": 1000,
            },
            "storage_iops_and_latency_where_applicable": {
                "status": "not_applicable",
                "rationale": "synthetic runtime has no storage path in this self-test",
            },
        },
    }


def _self_test() -> list[str]:
    raw = ROOT / ".mff-benchmark-raw-self-test.tmp"
    raw.write_bytes(b"MUSITU benchmark raw evidence self-test\n")
    try:
        raw_ref = raw.relative_to(ROOT).as_posix()
        digest = "sha256:" + ("1" * 64)
        row = {
            "image_digest": digest,
            "manifest_path": "deploy/example.json",
            "resource_profile": "deploy/resource-profile.json",
        }
        payload = _valid_synthetic_payload(
            raw_ref,
            hashlib.sha256(raw.read_bytes()).hexdigest(),
            digest,
            row,
        )
        errors = evidence_errors("self-test", row, payload)
        if errors:
            return [f"valid synthetic evidence rejected: {errors}"]

        failures: list[str] = []
        mutations: list[tuple[str, object]] = [
            ("runtime_key", "wrong-runtime"),
            ("authoritative_runtime_base_commit", "0" * 40),
            ("image_digest", "sha256:" + ("3" * 64)),
            ("executed_at", "2026-09-12T00:00:00"),
            ("raw_evidence_ref", "missing/raw-evidence.json"),
            ("raw_evidence_sha256", "4" * 64),
        ]
        for field, value in mutations:
            candidate = json.loads(json.dumps(payload))
            candidate[field] = value
            if not evidence_errors("self-test", row, candidate):
                failures.append(f"self-test failed to reject {field} drift")

        candidate = json.loads(json.dumps(payload))
        candidate["load_model"]["request_or_message_rate"] = "self-test"
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject placeholder load-model value")

        candidate = json.loads(json.dumps(payload))
        candidate["measurements"]["cpu_p50"] = "self-test"
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject placeholder measurement value")

        candidate = json.loads(json.dumps(payload))
        candidate["measurements"]["latency_p50"]["value"] = 50
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject invalid latency percentile ordering")

        candidate = json.loads(json.dumps(payload))
        candidate["measurements"]["cpu_p95"]["sample_count"] = 999
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject percentile sample-count drift")

        candidate = json.loads(json.dumps(payload))
        candidate["measurements"]["error_rate"]["value"] = 0.5
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject inconsistent error-rate evidence")

        candidate = json.loads(json.dumps(payload))
        candidate["load_model"]["failure_or_restart_scenario"]["performed"] = False
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject unperformed failure/restart scenario")

        candidate = json.loads(json.dumps(payload))
        candidate["measurements"]["restart_recovery_time"]["iterations"] = 2
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject restart iteration drift")

        candidate = json.loads(json.dumps(payload))
        candidate["measurements"]["storage_iops_and_latency_where_applicable"] = {
            "status": "not_applicable"
        }
        if not evidence_errors("self-test", row, candidate):
            failures.append("self-test failed to reject not-applicable evidence without rationale")
        return failures
    finally:
        raw.unlink(missing_ok=True)


def _contract_errors() -> list[str]:
    errors = _policy_errors() + _plan_errors()
    contract = _load(CONTRACT)
    if contract.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("runtime contract is not anchored to the sealed release")
        return errors
    measured = 0
    for row in contract.get("runtimes", []):
        if not isinstance(row, dict) or row.get("benchmark_status", "unmeasured") != "measured":
            continue
        measured += 1
        key = str(row.get("key", "unknown"))
        evidence_path = _repo_file(row.get("benchmark_evidence_ref"))
        if evidence_path is None:
            errors.append(f"{key}: measured benchmark lacks an existing benchmark_evidence_ref")
            continue
        try:
            payload = _load(evidence_path)
        except Exception as exc:
            errors.append(f"{key}: benchmark evidence is unreadable or invalid JSON ({type(exc).__name__})")
            continue
        errors.extend(f"{key}: {error}" for error in evidence_errors(key, row, payload))
    if not errors:
        print(f"PASS: semantic + raw benchmark evidence integrity gate validated {measured} measured runtime evidence rows")
        if measured == 0:
            print("BOUNDARY: no runtime currently claims measured benchmark status")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate byte-bound, semantically structured benchmark evidence for provider-neutral target staging."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--contract", action="store_true")
    args = parser.parse_args()
    errors = _self_test() if args.self_test else _contract_errors()
    if errors:
        for error in errors:
            print(f"BENCHMARK EVIDENCE BLOCKER: {error}")
        return 5
    if args.self_test:
        print(
            "PASS: benchmark evidence self-test rejects placeholder load/measurement values, "
            "semantic inconsistency, applicability drift, and raw-evidence mismatch"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
