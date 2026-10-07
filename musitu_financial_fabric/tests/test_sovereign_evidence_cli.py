from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys


def test_evidence_registration_cli_hashes_file_and_never_promotes(tmp_path):
    source = tmp_path / "operator-spec.bin"
    source.write_bytes(b"operator-evidence-bytes-v1\n")
    output = tmp_path / "record.json"
    db_path = tmp_path / "evidence.db"

    env = dict(os.environ)
    env["MUSITU_ENV"] = "sandbox"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/register_sovereign_evidence.py",
            "--profile",
            "zimbabwe-2026",
            "--dependency",
            "national_switch_message_interface",
            "--file",
            str(source),
            "--evidence-ref",
            "operator:zimswitch:spec-cli-v1",
            "--authority",
            "Zimswitch Technologies",
            "--version",
            "v1",
            "--source-location",
            "secure-room/spec-cli-v1.bin",
            "--actor",
            "evidence-intake",
            "--db-path",
            str(db_path),
            "--output",
            str(output),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["status"] == "registered"
    assert record["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()

    import sqlite3

    conn = sqlite3.connect(db_path)
    dependency = conn.execute(
        """SELECT status FROM country_profile_dependencies
           WHERE profile_key=? AND dependency_key=?""",
        ("zimbabwe-2026", "national_switch_message_interface"),
    ).fetchone()
    conn.close()
    assert dependency is None


def test_evidence_registration_cli_refuses_production_environment(tmp_path):
    source = tmp_path / "operator-spec.bin"
    source.write_bytes(b"operator-evidence\n")

    env = dict(os.environ)
    env["MUSITU_ENV"] = "production"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/register_sovereign_evidence.py",
            "--profile",
            "zimbabwe-2026",
            "--dependency",
            "national_switch_message_interface",
            "--file",
            str(source),
            "--evidence-ref",
            "operator:zimswitch:prod-refusal",
            "--authority",
            "Zimswitch Technologies",
            "--version",
            "v1",
            "--source-location",
            "secure-room/prod-refusal.bin",
            "--actor",
            "evidence-intake",
            "--db-path",
            str(tmp_path / "prod.db"),
            "--output",
            str(tmp_path / "out.json"),
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "sandbox" in (result.stderr + result.stdout).lower()
