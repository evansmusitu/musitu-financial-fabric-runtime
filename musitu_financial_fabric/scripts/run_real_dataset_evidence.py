from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.real_dataset_evidence import scan_ulb_arff


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MUSITU real-dataset evidence validation.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-url", default="")
    parser.add_argument("--source-id", default="")
    args = parser.parse_args()

    report = scan_ulb_arff(args.dataset)
    report["provenance"] = {
        "source_url": args.source_url,
        "source_id": args.source_id,
        "raw_dataset_committed_to_git": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
