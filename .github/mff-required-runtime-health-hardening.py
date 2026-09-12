from __future__ import annotations

import subprocess
from pathlib import Path

BASE_COMMIT = "52c9e02a92805cb03097112806d3b8095a8df2d0"
TEMP_VALIDATOR_FILES = {
    ".github/mff-required-runtime-health-hardening.py",
    ".github/workflows/mff-required-runtime-health-validator.yml",
}

def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"FAIL: {path} anchor count={count}, expected exactly 1")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")

ancestor = subprocess.run(
    ["git", "merge-base", "--is-ancestor", BASE_COMMIT, "HEAD"],
    check=False,
)
if ancestor.returncode != 0:
    raise SystemExit(f"FAIL: base authority {BASE_COMMIT} is not an ancestor of validator HEAD")
changed_since_base = {
    line.strip()
    for line in subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_COMMIT}..HEAD"],
        text=True,
    ).splitlines()
    if line.strip()
}
if not changed_since_base or not changed_since_base.issubset(TEMP_VALIDATOR_FILES):
    raise SystemExit(
        "FAIL: validator commits since base contain non-temporary changes: "
        + ", ".join(sorted(changed_since_base))
    )

replace_once(
    "musitu_financial_fabric/app/production.py",
    """_REQUIRED_DEPLOYMENT_EVIDENCE = (
    "dark_deployment",
    "monitoring_alerting",""",
    """_REQUIRED_DEPLOYMENT_EVIDENCE = (
    "dark_deployment",
    "required_runtime_health",
    "monitoring_alerting",""",
)

replace_once(
    "musitu_financial_fabric/infra/production_guard.tf",
    """  deployment_required_evidence = [
    "dark_deployment",
    "monitoring_alerting",""",
    """  deployment_required_evidence = [
    "dark_deployment",
    "required_runtime_health",
    "monitoring_alerting",""",
)

replace_once(
    "musitu_financial_fabric/tests/test_production_controls.py",
    """    provider_kill_independent: bool = True,
    target_environment_id: str = "test-only-production-target",
) -> tuple[str, str]:""",
    """    provider_kill_independent: bool = True,
    target_environment_id: str = "test-only-production-target",
    required_runtime_health_status: str = "passed",
) -> tuple[str, str]:""",
)

replace_once(
    "musitu_financial_fabric/tests/test_production_controls.py",
    """            "dark_deployment": {"status": "passed", "evidence_ref": "TEST-ONLY-DARK"},
            "monitoring_alerting":""",
    """            "dark_deployment": {"status": "passed", "evidence_ref": "TEST-ONLY-DARK"},
            "required_runtime_health": {
                "status": required_runtime_health_status,
                "evidence_ref": "TEST-ONLY-REQUIRED-RUNTIME-HEALTH",
            },
            "monitoring_alerting":""",
)

replace_once(
    "musitu_financial_fabric/tests/test_production_controls.py",
    """def test_live_funds_closed_without_external_evidence():
""",
    """def test_required_runtime_health_evidence_is_fail_closed(tmp_path):
    path, digest = _approved_manifest(tmp_path, funds_scope="production")
    deployment_path, deployment_digest = _passed_deployment_manifest(
        tmp_path,
        authorization_digest=digest,
        required_runtime_health_status="pending",
    )
    cfg = _base_production(
        production_mode="live",
        authorization_manifest_path=path,
        authorization_manifest_sha256=digest,
        deployment_evidence_manifest_path=deployment_path,
        deployment_evidence_manifest_sha256=deployment_digest,
    )
    result = production_readiness(cfg)
    assert result["ready_for_live_funds"] is False
    assert any(
        row["key"] == "deployment_required_runtime_health" and not row["ok"]
        for row in result["checks"]
    )
    with pytest.raises(ProductionGateError, match="deployment_required_runtime_health"):
        assert_live_funds_allowed(cfg)


def test_live_funds_closed_without_external_evidence():
""",
)

replace_once(
    "control/musitu-financial-fabric/production-deployment-evidence-manifest.example.json",
    """    "dark_deployment": {
      "status": "pending",
      "evidence_ref": ""
    },
    "monitoring_alerting":""",
    """    "dark_deployment": {
      "status": "pending",
      "evidence_ref": ""
    },
    "required_runtime_health": {
      "status": "pending",
      "evidence_ref": ""
    },
    "monitoring_alerting":""",
)

replace_once(
    "docs/production-readiness/ACTIVATION_RUNBOOK.md",
    """- executed dark-deployment, monitoring/alerting, PostgreSQL backup/restore, TigerBeetle recovery, provider reconciliation, and activation/rollback evidence references;
""",
    """- executed dark-deployment evidence plus a distinct `required_runtime_health` evidence reference proving every mandatory runtime component healthy on that exact target;
- executed monitoring/alerting, PostgreSQL backup/restore, TigerBeetle recovery, provider reconciliation, and activation/rollback evidence references;
""",
)

replace_once(
    "docs/production-readiness/CONTROL_MATRIX.md",
    """| Executed target controls | The target manifest must reference passed dark-deployment, monitoring/alerting, PostgreSQL backup/restore, TigerBeetle recovery, provider reconciliation, and activation/rollback drills |
""",
    """| Required runtime health on target | The target manifest must separately reference evidence that every mandatory runtime component was healthy on the exact immutable target; a generic dark-deployment pass is insufficient |
| Executed target controls | The target manifest must reference passed dark-deployment, monitoring/alerting, PostgreSQL backup/restore, TigerBeetle recovery, provider reconciliation, and activation/rollback drills |
""",
)

replace_once(
    ".github/workflows/musitu-financial-fabric-production-iac.yml",
    """              "dark_deployment": {"status": "passed", "evidence_ref": "TEST-ONLY-DARK"},
              "monitoring_alerting":""",
    """              "dark_deployment": {"status": "passed", "evidence_ref": "TEST-ONLY-DARK"},
              "required_runtime_health": {"status": "passed", "evidence_ref": "TEST-ONLY-REQUIRED-RUNTIME-HEALTH"},
              "monitoring_alerting":""",
)

replace_once(
    ".github/workflows/musitu-financial-fabric-production-iac.yml",
    """          tampered_bundle="$RUNNER_TEMP/target-evidence-bundle-tampered-ci.bin"
""",
    """          missing_runtime_health="$RUNNER_TEMP/production-deployment-missing-runtime-health-ci.json"
          python - "$deployment" "$missing_runtime_health" <<'PY'
          import json, sys
          source, target = sys.argv[1], sys.argv[2]
          data = json.load(open(source))
          del data['evidence']['required_runtime_health']
          json.dump(data, open(target, 'w'), sort_keys=True)
          PY
          missing_runtime_health_digest="$(sha256sum "$missing_runtime_health" | awk '{print $1}')"
          if tofu -chdir=infra plan -input=false -lock=false -refresh=false \
            -var='environment=production' \
            -var='production_mode=pilot' \
            -var='live_funds_enabled=true' \
            -var="authorization_manifest_path=$manifest" \
            -var="authorization_manifest_sha256=$digest" \
            -var="deployment_evidence_manifest_path=$missing_runtime_health" \
            -var="deployment_evidence_manifest_sha256=$missing_runtime_health_digest" \
            -var='target_environment_id=test-only-production-target' \
            -var="release_commit=$release_commit" \
            -var="release_image_digest=$release_image" \
            -var='production_enabled_rails=["ecocash"]' \
            -var='production_enabled_currencies=["USD"]' \
            -var='max_single_payment_minor=1000' \
            > "$RUNNER_TEMP/missing-runtime-health.log" 2>&1; then
            echo 'FAIL: deployment evidence without required runtime health was accepted'
            exit 1
          fi
          assert_log_contains "$RUNNER_TEMP/missing-runtime-health.log" 'executed target-environment drills'

          tampered_bundle="$RUNNER_TEMP/target-evidence-bundle-tampered-ci.bin"
""",
)

replace_once(
    ".github/workflows/musitu-financial-fabric-production-iac.yml",
    """          echo 'PASS: IaC fail-closed guards require exact external authorization, authorization-evidence bundle integrity, target-deployment evidence, and target-evidence bundle integrity'
""",
    """          echo 'PASS: IaC fail-closed guards require exact external authorization, authorization-evidence bundle integrity, target identity, full required-runtime health evidence, target-deployment evidence, and target-evidence bundle integrity'
""",
)

print("PATCH_APPLIED")
