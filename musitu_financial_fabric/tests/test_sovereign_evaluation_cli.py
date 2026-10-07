from __future__ import annotations

import json
import os
import subprocess
import sys


def test_evaluation_pack_cli_generates_nonproduction_reference_pack(tmp_path):
    manifest = {
        "authority": "operator-supplied-reference",
        "interface_version": "draft",
        "source_evidence_ref": "operator-spec-placeholder",
        "behaviors": {
            "transfer_submit": {"supported": False, "mapping_ref": ""},
            "transfer_status": {"supported": False, "mapping_ref": ""},
            "idempotency": {"supported": False, "mapping_ref": ""},
            "participant_addressing": {"supported": False, "mapping_ref": ""},
            "exception_mapping": {"supported": False, "mapping_ref": ""},
            "settlement_reference": {"supported": False, "mapping_ref": ""},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "evaluation.json"
    db_path = tmp_path / "evaluation.db"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    env = dict(os.environ)
    env["MUSITU_ENV"] = "sandbox"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_sovereign_evaluation_pack.py",
            "--profile",
            "zimbabwe-2026",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
            "--db-path",
            str(db_path),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    pack = json.loads(output_path.read_text(encoding="utf-8"))
    assert pack["profile_key"] == "zimbabwe-2026"
    assert pack["adapter_conformance"]["adapter_ready"] is False
    assert len(pack["country_blockers"]) == 5
    assert all(
        item["status"] == "reference"
        for item in pack["adapter_conformance"]["country_dependencies"].values()
    )
    assert pack["uat"]["live_funds_moved"] is False
    assert pack["uat"]["production_authorized"] is False
    assert pack["production_authorized"] is False
    assert pack["claim_boundaries"]["rbz_approved"] is False
    assert pack["claim_boundaries"]["zimswitch_authorized"] is False


def test_evaluation_pack_cli_refuses_production_environment(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "authority": "reference",
                "interface_version": "draft",
                "source_evidence_ref": "reference",
                "behaviors": {},
            }
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["MUSITU_ENV"] = "production"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/generate_sovereign_evaluation_pack.py",
            "--profile",
            "zimbabwe-2026",
            "--manifest",
            str(manifest_path),
            "--output",
            str(tmp_path / "out.json"),
            "--db-path",
            str(tmp_path / "prod.db"),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "sandbox" in (result.stderr + result.stdout).lower()
