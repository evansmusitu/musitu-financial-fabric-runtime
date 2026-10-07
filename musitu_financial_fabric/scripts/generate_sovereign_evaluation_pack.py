from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a non-production MUSITU Sovereign Payments regulator evaluation pack."
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--db-path", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = os.getenv("MUSITU_ENV", "sandbox").strip().lower()
    if environment == "production":
        print(
            "This generator is sandbox/reference-only and refuses the production environment.",
            file=sys.stderr,
        )
        return 2

    manifest_path = Path(args.manifest)
    output_path = Path(args.output)
    db_path = Path(args.db_path)

    if not manifest_path.is_file():
        print(f"Manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Invalid manifest: {exc}", file=sys.stderr)
        return 2

    os.environ["MUSITU_ENV"] = "sandbox"
    os.environ["MUSITU_DB_PATH"] = str(db_path)
    os.environ.pop("MUSITU_METADATA_DB_URL", None)

    from app import db
    from app.sovereign_conformance import build_regulator_evaluation_pack
    from app.sovereign_uat import run_reference_uat

    db.init_db()
    uat = run_reference_uat("regulator-evaluation-pack")
    pack = build_regulator_evaluation_pack(args.profile, manifest, uat)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(pack, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
