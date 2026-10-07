from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register hash-bound MUSITU Sovereign Payments evidence in a sandbox evidence ledger."
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--dependency", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-location", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = os.getenv("MUSITU_ENV", "sandbox").strip().lower()
    if environment == "production":
        print(
            "This evidence-registration CLI is sandbox/reference-only and refuses the production environment.",
            file=sys.stderr,
        )
        return 2

    source = Path(args.file)
    output = Path(args.output)
    db_path = Path(args.db_path)

    if not source.is_file():
        print(f"Evidence file not found: {source}", file=sys.stderr)
        return 2

    os.environ["MUSITU_ENV"] = "sandbox"
    os.environ["MUSITU_DB_PATH"] = str(db_path)
    os.environ.pop("MUSITU_METADATA_DB_URL", None)

    from app import db
    from app.sovereign_evidence import register_country_profile_evidence_file

    db.init_db()
    try:
        record = register_country_profile_evidence_file(
            args.profile,
            args.dependency,
            file_path=source,
            evidence_ref=args.evidence_ref,
            source_authority=args.authority,
            source_version=args.version,
            source_location=args.source_location,
            actor=args.actor,
        )
    except Exception as exc:
        print(f"Evidence registration failed: {exc}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
