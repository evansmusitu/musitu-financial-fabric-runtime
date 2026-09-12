from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "musitu_financial_fabric" / "scripts"
TARGET = ROOT / "deploy" / "musitu-financial-fabric" / "provider-neutral"
POLICY = TARGET / "deployability-composition-policy.json"
EXPECTED_BASE_COMMIT = "80c72d9f711561dd46337d7286ee7bfb2bb5e658"
POLICY_SCHEMA = "mff.deployability-composition-policy.v1"
EXPECTED_SEMANTIC_GATES = (
    ("benchmark_evidence", "validate_benchmark_evidence.py"),
    ("recovery_profiles", "validate_recovery_profiles.py"),
    ("identity_secret_profiles", "validate_identity_secret_profiles.py"),
    ("operational_profiles", "validate_operational_profiles.py"),
    ("supply_persistence_profiles", "validate_supply_persistence_profiles.py"),
    ("resource_profiles", "validate_resource_profiles.py"),
    ("manifest_profiles", "validate_manifest_profiles.py"),
)
STRUCTURAL_GATE = "validate_provider_neutral_target.py"
RunCallable = Callable[..., Any]


def _load_policy() -> Any:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _policy_errors() -> list[str]:
    errors: list[str] = []
    try:
        policy = _load_policy()
    except Exception as exc:
        return [f"deployability composition policy unavailable or invalid JSON: {type(exc).__name__}"]
    if not isinstance(policy, dict):
        return ["deployability composition policy root must be an object"]
    if policy.get("schema_version") != POLICY_SCHEMA:
        errors.append("deployability composition policy schema_version is invalid")
    if policy.get("authoritative_runtime_base_commit") != EXPECTED_BASE_COMMIT:
        errors.append("deployability composition policy is not anchored to the sealed runtime release")

    expected_semantic = [
        {"name": name, "script": f"musitu_financial_fabric/scripts/{script}", "args": ["--contract"]}
        for name, script in EXPECTED_SEMANTIC_GATES
    ]
    if policy.get("semantic_contract_gates") != expected_semantic:
        errors.append("semantic contract gate inventory does not exactly match validator policy")

    expected_structural = {
        "script": f"musitu_financial_fabric/scripts/{STRUCTURAL_GATE}",
        "args": ["--deployable"],
        "non_deployable_exit": 3,
    }
    if policy.get("structural_deployability_gate") != expected_structural:
        errors.append("structural deployability gate does not exactly match validator policy")

    for _, script in EXPECTED_SEMANTIC_GATES:
        if not (SCRIPTS / script).is_file():
            errors.append(f"semantic gate script is missing: {script}")
    if not (SCRIPTS / STRUCTURAL_GATE).is_file():
        errors.append(f"structural deployability gate script is missing: {STRUCTURAL_GATE}")
    return errors


def _execute(
    script: Path,
    args: list[str],
    *,
    runner: RunCallable | None = None,
) -> Any:
    execute = subprocess.run if runner is None else runner
    return execute(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _first_output(result: Any) -> str:
    merged = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}"
    for line in merged.splitlines():
        value = line.strip()
        if value:
            return value[:500]
    return "no diagnostic output"


def _semantic_gate_errors(*, runner: RunCallable | None = None) -> list[str]:
    errors: list[str] = []
    for name, script_name in EXPECTED_SEMANTIC_GATES:
        script = SCRIPTS / script_name
        try:
            result = _execute(script, ["--contract"], runner=runner)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{name}: could not execute semantic gate ({type(exc).__name__})")
            continue
        if int(getattr(result, "returncode", 1)) != 0:
            errors.append(
                f"{name}: semantic gate failed with exit {getattr(result, 'returncode', 'unknown')}: "
                f"{_first_output(result)}"
            )
    return errors


def _self_test() -> list[str]:
    failures = _policy_errors()
    if failures:
        return failures

    class SyntheticResult:
        returncode = 9
        stdout = "synthetic semantic failure"
        stderr = ""

    def failing_runner(*args: Any, **kwargs: Any) -> SyntheticResult:
        return SyntheticResult()

    synthetic = _semantic_gate_errors(runner=failing_runner)
    if len(synthetic) != len(EXPECTED_SEMANTIC_GATES):
        failures.append("composition self-test did not fail closed for every synthetic semantic gate failure")
    if any("synthetic semantic failure" not in item for item in synthetic):
        failures.append("composition self-test did not preserve semantic gate diagnostic evidence")
    return failures


def _contract() -> int:
    policy_errors = _policy_errors()
    if policy_errors:
        for error in policy_errors:
            print(f"COMPOSITION BLOCKER: {error}")
        return 7

    semantic_errors = _semantic_gate_errors()
    if semantic_errors:
        for error in semantic_errors:
            print(f"COMPOSITION BLOCKER: {error}")
        return 7

    print("PASS: all semantic contract gates passed before structural deployability evaluation")
    try:
        structural = _execute(SCRIPTS / STRUCTURAL_GATE, ["--deployable"])
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"COMPOSITION BLOCKER: structural deployability gate could not execute ({type(exc).__name__})")
        return 7

    if getattr(structural, "stdout", ""):
        print(structural.stdout, end="" if structural.stdout.endswith("\n") else "\n")
    if getattr(structural, "stderr", ""):
        print(structural.stderr, end="" if structural.stderr.endswith("\n") else "\n", file=sys.stderr)

    rc = int(getattr(structural, "returncode", 1))
    if rc in (0, 3):
        return rc
    print(f"COMPOSITION BLOCKER: structural deployability gate returned unexpected exit {rc}")
    return 7


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Canonical fail-closed provider-neutral deployability composition gate."
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
        print("PASS: canonical deployability composition gate fails closed on semantic-gate failure")
        return 0
    return _contract()


if __name__ == "__main__":
    raise SystemExit(main())
