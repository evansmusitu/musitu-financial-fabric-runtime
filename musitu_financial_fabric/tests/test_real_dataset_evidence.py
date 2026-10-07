from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.real_dataset_evidence import (
    EvidenceError,
    amount_to_minor_exact,
    build_ulb_instruction,
    scan_ulb_arff,
)


ARFF = """@relation credit-card-fraud-detection
@attribute Time numeric
@attribute V1 numeric
@attribute V2 numeric
@attribute Amount numeric
@attribute Class numeric
@data
0,-1.0,0.1,149.62,0
1,0.2,-0.1,0.00,0
2,2.0,3.0,1.25,1
3,1.0,1.0,10.10,0
"""


def test_exact_amount_to_minor_conversion_rejects_fractional_minor_units():
    assert amount_to_minor_exact("149.62") == 14962
    assert amount_to_minor_exact("0.00") == 0
    assert amount_to_minor_exact(Decimal("1.25")) == 125
    with pytest.raises(EvidenceError, match="minor-unit"):
        amount_to_minor_exact("1.001")


def test_ulb_instruction_uses_real_amount_but_explicit_no_currency_code():
    instruction = build_ulb_instruction(
        row_number=7,
        time_value="42",
        amount_minor=1234,
    )
    assert instruction.amount_minor == 1234
    assert instruction.currency == "XXX"
    assert instruction.idempotency_key == "ulb-2013:7"
    assert instruction.reference == "ulb-2013:row:7:time:42"


def test_scan_ulb_arff_streams_counts_fraud_zero_amounts_and_fingerprint(tmp_path):
    path = tmp_path / "ulb.arff"
    path.write_text(ARFF, encoding="utf-8")

    report = scan_ulb_arff(path)

    assert report["dataset"]["row_count"] == 4
    assert report["dataset"]["fraud_count"] == 1
    assert report["dataset"]["legitimate_count"] == 3
    assert report["amounts"]["zero_amount_count"] == 1
    assert report["amounts"]["nonzero_amount_count"] == 3
    assert report["amounts"]["total_minor"] == 16097
    assert report["amounts"]["min_nonzero_minor"] == 125
    assert report["amounts"]["max_nonzero_minor"] == 14962
    assert report["time"]["first"] == "0"
    assert report["time"]["last"] == "3"
    assert report["validation"]["switch_instruction_count"] == 3
    assert report["validation"]["malformed_count"] == 0
    assert len(report["dataset"]["file_sha256"]) == 64
    assert len(report["dataset"]["row_fingerprint_sha256"]) == 64

    second = scan_ulb_arff(path)
    assert second["dataset"]["row_fingerprint_sha256"] == report["dataset"]["row_fingerprint_sha256"]


def test_scan_ulb_arff_rejects_missing_required_columns(tmp_path):
    path = tmp_path / "bad.arff"
    path.write_text(
        """@relation bad
@attribute Time numeric
@attribute Amount numeric
@data
0,1.00
""",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="required columns"):
        scan_ulb_arff(path)


def test_scan_ulb_arff_rejects_unknown_class_label(tmp_path):
    path = tmp_path / "bad-class.arff"
    path.write_text(
        """@relation bad
@attribute Time numeric
@attribute Amount numeric
@attribute Class numeric
@data
0,1.00,2
""",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="class label"):
        scan_ulb_arff(path)
