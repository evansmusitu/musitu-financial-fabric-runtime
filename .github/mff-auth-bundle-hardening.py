from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected one match, found {count}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')

replace_once(
    'musitu_financial_fabric/app/production.py',
    '''    checks = [ProductionCheck("authorization_manifest", True, "external", "pinned authorization manifest verified")]\n    evidence = manifest.get("evidence")\n''',
    '''    checks = [ProductionCheck("authorization_manifest", True, "external", "pinned authorization manifest verified")]\n\n    evidence_bundle = manifest.get("evidence_bundle")\n    bundle_ok = False\n    bundle_message = "authorization evidence bundle path and SHA-256 are missing or malformed"\n    if isinstance(evidence_bundle, dict):\n        bundle_path_raw = evidence_bundle.get("path")\n        bundle_sha256 = str(evidence_bundle.get("sha256", "")).strip().lower()\n        if isinstance(bundle_path_raw, str) and bundle_path_raw.strip() and _SHA256_RE.fullmatch(bundle_sha256):\n            try:\n                bundle_raw = Path(bundle_path_raw.strip()).read_bytes()\n                actual_bundle_sha256 = hashlib.sha256(bundle_raw).hexdigest()\n                bundle_ok = actual_bundle_sha256 == bundle_sha256\n                bundle_message = (\n                    "byte-pinned authorization evidence bundle verified"\n                    if bundle_ok\n                    else "authorization evidence bundle SHA-256 mismatch"\n                )\n            except OSError as exc:\n                bundle_message = f"authorization evidence bundle unavailable: {type(exc).__name__}"\n    checks.append(ProductionCheck(\n        "authorization_evidence_bundle",\n        bundle_ok,\n        "external",\n        bundle_message,\n    ))\n\n    evidence = manifest.get("evidence")\n'''
)

replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    '''  authorization_hash_matches = (\n    local.authorization_manifest_present &&\n    can(regex("^[0-9a-fA-F]{64}$", var.authorization_manifest_sha256)) &&\n    lower(var.authorization_manifest_sha256) == sha256(local.authorization_manifest_raw)\n  )\n\n  required_evidence = ["regulator", "sponsor_bank", "data_protection", "independent_security", "rail_provider"]\n''',
    '''  authorization_hash_matches = (\n    local.authorization_manifest_present &&\n    can(regex("^[0-9a-fA-F]{64}$", var.authorization_manifest_sha256)) &&\n    lower(var.authorization_manifest_sha256) == sha256(local.authorization_manifest_raw)\n  )\n  authorization_evidence_bundle_path   = trimspace(try(local.authorization_manifest.evidence_bundle.path, ""))\n  authorization_evidence_bundle_sha256 = lower(trimspace(try(local.authorization_manifest.evidence_bundle.sha256, "")))\n  authorization_evidence_bundle_hash_matches = (\n    local.authorization_evidence_bundle_path != "" &&\n    can(regex("^[0-9a-fA-F]{64}$", local.authorization_evidence_bundle_sha256)) &&\n    try(filesha256(local.authorization_evidence_bundle_path) == local.authorization_evidence_bundle_sha256, false)\n  )\n\n  required_evidence = ["regulator", "sponsor_bank", "data_protection", "independent_security", "rail_provider"]\n'''
)
replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    '''        local.authorization_hash_matches &&\n        local.evidence_approved &&\n''',
    '''        local.authorization_hash_matches &&\n        local.authorization_evidence_bundle_hash_matches &&\n        local.evidence_approved &&\n'''
)
replace_once(
    'musitu_financial_fabric/infra/production_guard.tf',
    '''      error_message = "Live funds require a byte-pinned, unexpired external authorization manifest whose approved evidence, funds scope, rails, currencies, and single-payment ceiling contain the exact deployment perimeter."\n''',
    '''      error_message = "Live funds require a byte-pinned, unexpired external authorization manifest and byte-pinned authorization evidence bundle whose approved evidence, funds scope, rails, currencies, and single-payment ceiling contain the exact deployment perimeter."\n'''
)

replace_once(
    'musitu_financial_fabric/tests/test_production_controls.py',
    ''') -> tuple[str, str]:\n    manifest = {\n        "funds_scope": funds_scope,\n''',
    ''') -> tuple[str, str]:\n    evidence_bundle_path = tmp_path / f"authorization-evidence-{funds_scope}.bin"\n    evidence_bundle_raw = b"test-only-authorization-evidence-bundle"\n    evidence_bundle_path.write_bytes(evidence_bundle_raw)\n    manifest = {\n        "funds_scope": funds_scope,\n        "evidence_bundle": {\n            "path": str(evidence_bundle_path),\n            "sha256": hashlib.sha256(evidence_bundle_raw).hexdigest(),\n        },\n'''
)
replace_once(
    'musitu_financial_fabric/tests/test_production_controls.py',
    '''def test_external_authorization_alone_cannot_open_without_target_deployment_evidence(tmp_path):\n''',
    '''def test_authorization_evidence_bundle_pin_is_fail_closed(tmp_path):\n    path, digest = _approved_manifest(tmp_path, funds_scope="production")\n    deployment_path, deployment_digest = _passed_deployment_manifest(tmp_path, authorization_digest=digest)\n    authorization_manifest = json.loads(open(path, encoding="utf-8").read())\n    evidence_bundle_path = authorization_manifest["evidence_bundle"]["path"]\n    with open(evidence_bundle_path, "ab") as handle:\n        handle.write(b"tampered")\n    cfg = _base_production(\n        production_mode="live",\n        authorization_manifest_path=path,\n        authorization_manifest_sha256=digest,\n        deployment_evidence_manifest_path=deployment_path,\n        deployment_evidence_manifest_sha256=deployment_digest,\n    )\n    result = production_readiness(cfg)\n    assert result["ready_for_live_funds"] is False\n    assert any(row["key"] == "authorization_evidence_bundle" and not row["ok"] for row in result["checks"])\n\n\ndef test_external_authorization_alone_cannot_open_without_target_deployment_evidence(tmp_path):\n'''
)

replace_once(
    'control/musitu-financial-fabric/production-authorization-manifest.example.json',
    '''  "expires_at": "REPLACE-WITH-RFC3339-UTC-EXPIRY",\n  "launch_scope": {\n''',
    '''  "expires_at": "REPLACE-WITH-RFC3339-UTC-EXPIRY",\n  "evidence_bundle": {\n    "path": "REPLACE-WITH-MOUNTED-AUTHORIZATION-EVIDENCE-BUNDLE-PATH",\n    "sha256": "REPLACE-WITH-64-HEX-AUTHORIZATION-EVIDENCE-BUNDLE-SHA256"\n  },\n  "launch_scope": {\n'''
)
replace_once(
    'control/musitu-financial-fabric/production-authorization-manifest.example.json',
    '''  "notes": "Example structure only. Replace every pending field and the expiry with authentic externally retained evidence before pinning this manifest. Never commit credentials or confidential authorization material."\n''',
    '''  "notes": "Example structure only. Retain the authentic external approval documents as a dedicated read-only evidence bundle, record its exact mounted path and SHA-256, replace every pending field and the expiry, then pin this manifest. Matching hashes prove byte integrity only; they do not prove issuer authenticity or create authorization. Never commit credentials or confidential authorization material."\n'''
)

replace_once(
    'docs/production-readiness/ACTIVATION_RUNBOOK.md',
    '''Create the deployed authorization manifest from the repository example only after authentic evidence exists. Compute the exact SHA-256 of that deployed file and configure both:\n''',
    '''Create the deployed authorization manifest from the repository example only after authentic evidence exists. Retain the actual regulator/bank/data-protection/security/rail approval artifacts as a dedicated evidence bundle outside the source repository, mount that exact bundle read-only where the production gate can read it, compute its SHA-256, and record both path and digest under `evidence_bundle`. Missing, unreadable, or modified authorization evidence must keep the funds gate closed.\n\nCompute the exact SHA-256 of the deployed authorization manifest and configure both:\n'''
)
replace_once(
    'docs/production-readiness/CONTROL_MATRIX.md',
    '''| Production evidence | Authorization manifest must be external to the repo and SHA-256 pinned |\n''',
    '''| Production evidence | Authorization manifest must be external to the repo and SHA-256 pinned |\n| Authorization evidence bundle integrity | The authorization manifest must name a read-only mounted evidence bundle and SHA-256; runtime and IaC fail closed if the exact retained approval bundle is absent or its bytes do not match |\n'''
)
replace_once(
    'docs/production-readiness/README.md',
    '''Real-funds readiness now has two independent pinned evidence inputs: the external authorization manifest and a target-deployment evidence manifest.''',
    '''Real-funds readiness now has independently pinned authorization and target-deployment evidence inputs. The authorization manifest must also bind a read-only mounted authorization-evidence bundle by exact SHA-256, just as the target-deployment manifest binds its target-evidence bundle.'''
)

# IaC workflow: construct a byte-pinned test-only authorization evidence bundle.
replace_once(
    '.github/workflows/musitu-financial-fabric-production-iac.yml',
    '''          manifest="$RUNNER_TEMP/production-authorization-ci.json"\n          cat > "$manifest" <<'JSON'\n          {\n            "funds_scope": "pilot",\n            "expires_at": "2099-01-01T00:00:00Z",\n''',
    '''          authorization_bundle="$RUNNER_TEMP/authorization-evidence-bundle-ci.bin"\n          printf '%s' 'TEST-ONLY-AUTHORIZATION-EVIDENCE-BUNDLE' > "$authorization_bundle"\n          authorization_bundle_digest="$(sha256sum "$authorization_bundle" | awk '{print $1}')"\n\n          manifest="$RUNNER_TEMP/production-authorization-ci.json"\n          cat > "$manifest" <<JSON\n          {\n            "funds_scope": "pilot",\n            "expires_at": "2099-01-01T00:00:00Z",\n            "evidence_bundle": {\n              "path": "$authorization_bundle",\n              "sha256": "$authorization_bundle_digest"\n            },\n'''
)
replace_once(
    '.github/workflows/musitu-financial-fabric-production-iac.yml',
    '''          assert_log_contains "$RUNNER_TEMP/tampered-evidence-bundle.log" 'byte-pinned target evidence bundle'\n\n          echo 'PASS: IaC fail-closed guards require exact external authorization, target-deployment evidence, and target evidence-bundle integrity'\n''',
    '''          assert_log_contains "$RUNNER_TEMP/tampered-evidence-bundle.log" 'byte-pinned target evidence bundle'\n\n          printf '%s' '-TAMPERED' >> "$authorization_bundle"\n          if tofu -chdir=infra plan -input=false -lock=false -refresh=false "${common[@]}" \\\n            > "$RUNNER_TEMP/tampered-authorization-bundle.log" 2>&1; then\n            echo 'FAIL: tampered authorization evidence bundle was accepted'\n            exit 1\n          fi\n          assert_log_contains "$RUNNER_TEMP/tampered-authorization-bundle.log" 'byte-pinned authorization evidence bundle'\n\n          echo 'PASS: IaC fail-closed guards require exact external authorization, authorization-evidence bundle integrity, target-deployment evidence, and target-evidence bundle integrity'\n'''
)
