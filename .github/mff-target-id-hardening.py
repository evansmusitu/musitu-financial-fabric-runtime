from pathlib import Path

ROOT = Path('.')

def replace_once(path, old, new):
    p = ROOT / path
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1))

replace_once(
    'musitu_financial_fabric/app/config.py',
    '    deployment_evidence_manifest_sha256: str = field(default_factory=lambda: _str("MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_SHA256").lower())\n'
    '    build_commit: str = field(default_factory=lambda: _str("MUSITU_BUILD_COMMIT").lower())\n',
    '    deployment_evidence_manifest_sha256: str = field(default_factory=lambda: _str("MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_SHA256").lower())\n'
    '    target_environment_id: str = field(default_factory=lambda: _str("MUSITU_TARGET_ENVIRONMENT_ID"))\n'
    '    build_commit: str = field(default_factory=lambda: _str("MUSITU_BUILD_COMMIT").lower())\n',
)

replace_once(
    'musitu_financial_fabric/app/production.py',
    '''    target_environment_id = manifest.get("target_environment_id")
    target_ok = isinstance(target_environment_id, str) and bool(target_environment_id.strip())
    checks.append(ProductionCheck(
        "deployment_target_identity",
        target_ok,
        "deployment",
        "target production environment has an explicit immutable evidence identity" if target_ok else "target production environment identity is missing",
    ))
''',
    '''    target_environment_id = manifest.get("target_environment_id")
    configured_target_id = cfg.target_environment_id.strip()
    target_ok = (
        bool(configured_target_id)
        and isinstance(target_environment_id, str)
        and target_environment_id.strip() == configured_target_id
    )
    checks.append(ProductionCheck(
        "deployment_target_identity",
        target_ok,
        "deployment",
        "target deployment evidence matches the configured immutable environment identity"
        if target_ok
        else "target deployment evidence does not match the configured immutable environment identity",
    ))
''',
)

replace_once(
    'musitu_financial_fabric/tests/test_production_controls.py',
    '        build_commit="a" * 40,\n        release_image_digest="sha256:" + "b" * 64,\n',
    '        build_commit="a" * 40,\n        release_image_digest="sha256:" + "b" * 64,\n        target_environment_id="test-only-production-target",\n',
)

replace_once(
    'musitu_financial_fabric/tests/test_production_controls.py',
    '    provider_kill_independent: bool = True,\n) -> tuple[str, str]:\n',
    '    provider_kill_independent: bool = True,\n    target_environment_id: str = "test-only-production-target",\n) -> tuple[str, str]:\n',
)

replace_once(
    'musitu_financial_fabric/tests/test_production_controls.py',
    '        "target_environment_id": "test-only-production-target",\n',
    '        "target_environment_id": target_environment_id,\n',
)

replace_once(
    'musitu_financial_fabric/tests/test_production_controls.py',
    'def test_target_deployment_manifest_pin_is_fail_closed(tmp_path):\n',
    '''def test_target_deployment_identity_must_match_configured_target(tmp_path):
    path, digest = _approved_manifest(tmp_path, funds_scope="production")
    deployment_path, deployment_digest = _passed_deployment_manifest(
        tmp_path,
        authorization_digest=digest,
        target_environment_id="wrong-production-target",
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
    assert any(row["key"] == "deployment_target_identity" and not row["ok"] for row in result["checks"])


def test_target_deployment_manifest_pin_is_fail_closed(tmp_path):
''',
)

replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    'variable "release_commit" {\n',
    '''variable "target_environment_id" {
  type        = string
  description = "Immutable identity of the exact production target this deployment is permitted to activate."
  default     = ""
}

variable "release_commit" {
''',
)

replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    '  deployment_target_identity = trimspace(try(local.deployment_manifest.target_environment_id, "")) != ""\n',
    '''  deployment_target_identity = (
    trimspace(var.target_environment_id) != "" &&
    trimspace(try(local.deployment_manifest.target_environment_id, "")) == trimspace(var.target_environment_id)
  )
''',
)

replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    '    release_commit           = lower(var.release_commit)\n',
    '    target_environment_id    = var.target_environment_id\n    release_commit           = lower(var.release_commit)\n',
)

replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    '      error_message = "Live funds require a byte-pinned target deployment evidence manifest and byte-pinned target evidence bundle bound to the exact release commit, immutable OCI digest, distinct rollback digest, external authorization pin, executed target-environment drills, and independent network/provider/settlement kill controls."\n',
    '      error_message = "Live funds require a byte-pinned target deployment evidence manifest and byte-pinned target evidence bundle bound to the exact configured target identity, release commit, immutable OCI digest, distinct rollback digest, external authorization pin, executed target-environment drills, and independent network/provider/settlement kill controls."\n',
)

replace_once(
    '.github/workflows/musitu-financial-fabric-production-iac.yml',
    '            -var="deployment_evidence_manifest_sha256=$deployment_digest"\n            -var="release_commit=$release_commit"\n',
    '            -var="deployment_evidence_manifest_sha256=$deployment_digest"\n            -var=\'target_environment_id=test-only-production-target\'\n            -var="release_commit=$release_commit"\n',
)

p = ROOT / '.github/workflows/musitu-financial-fabric-production-iac.yml'
text = p.read_text()
if text.count('"${common[@]:0:9}"') != 2:
    raise SystemExit(f"production-iac slice count changed: {text.count(chr(34) + '${common[@]:0:9}' + chr(34))}")
text = text.replace('"${common[@]:0:9}"', '"${common[@]:0:10}"')
p.write_text(text)

replace_once(
    '.github/workflows/musitu-financial-fabric-production-iac.yml',
    '          tofu -chdir=infra plan -input=false -lock=false -refresh=false "${common[@]}" \\\n            -out="$RUNNER_TEMP/valid.tfplan"\n\n',
    '''          tofu -chdir=infra plan -input=false -lock=false -refresh=false "${common[@]}" \\
            -out="$RUNNER_TEMP/valid.tfplan"

          wrong_target=("${common[@]}")
          wrong_target[7]="-var=target_environment_id=wrong-production-target"
          if tofu -chdir=infra plan -input=false -lock=false -refresh=false "${wrong_target[@]}" \\
            > "$RUNNER_TEMP/wrong-target.log" 2>&1; then
            echo 'FAIL: wrong production target identity was accepted'
            exit 1
          fi
          assert_log_contains "$RUNNER_TEMP/wrong-target.log" 'exact configured target identity'

''',
)

p = ROOT / '.github/workflows/musitu-financial-fabric-production-iac.yml'
lines = p.read_text().splitlines(True)
out = []
for i, line in enumerate(lines):
    out.append(line)
    if '-var="deployment_evidence_manifest_sha256=$' in line:
        nxt = lines[i + 1] if i + 1 < len(lines) else ''
        if 'target_environment_id=' not in nxt:
            out.append("            -var='target_environment_id=test-only-production-target' \\\n")
p.write_text(''.join(out))

replace_once(
    'docs/production-readiness/ACTIVATION_RUNBOOK.md',
    '- the exact runtime commit embedded in the image as `MUSITU_BUILD_COMMIT`;\n',
    '- the exact immutable production target identity configured independently as `MUSITU_TARGET_ENVIRONMENT_ID`;\n'
    '- the exact runtime commit embedded in the image as `MUSITU_BUILD_COMMIT`;\n',
)

replace_once(
    'docs/production-readiness/ACTIVATION_RUNBOOK.md',
    '- `MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_SHA256`\n',
    '- `MUSITU_DEPLOYMENT_EVIDENCE_MANIFEST_SHA256`\n- `MUSITU_TARGET_ENVIRONMENT_ID`\n',
)

replace_once(
    'docs/production-readiness/CONTROL_MATRIX.md',
    '| Target deployment evidence | Byte-pinned target manifest',
    '| Target identity binding | Deployment manifest target ID must exactly equal independently configured `MUSITU_TARGET_ENVIRONMENT_ID`; missing or mismatched identity closes live funds. | Automated runtime + IaC negative tests | Software control only; the configured ID must come from the real target environment. | Fail closed |\n| Target deployment evidence | Byte-pinned target manifest',
)

print('target identity hardening applied')
