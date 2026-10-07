from __future__ import annotations

import csv
import hashlib
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .switch_contracts import SwitchTransferInstruction


class EvidenceError(RuntimeError):
    pass


_REQUIRED_ULB_COLUMNS = ("Time", "Amount", "Class")


def amount_to_minor_exact(value: str | Decimal) -> int:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise EvidenceError("invalid monetary amount") from exc
    minor = amount * Decimal("100")
    integral = minor.to_integral_value()
    if minor != integral:
        raise EvidenceError("amount contains fractional minor-unit precision")
    return int(integral)


def build_ulb_instruction(*, row_number: int, time_value: str, amount_minor: int) -> SwitchTransferInstruction:
    return SwitchTransferInstruction(
        idempotency_key=f"ulb-2013:{row_number}",
        payer_participant_id="dataset-payer",
        payee_participant_id="dataset-payee",
        payer_alias="dataset-payer@ulb",
        payee_alias="dataset-payee@ulb",
        amount_minor=amount_minor,
        currency="XXX",
        reference=f"ulb-2013:row:{row_number}:time:{time_value}",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_attribute_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.lower().startswith("@attribute"):
        return None
    rest = stripped[len("@attribute"):].strip()
    if not rest:
        return None
    if rest[0] in {"'", '"'}:
        quote = rest[0]
        end = rest.find(quote, 1)
        if end <= 0:
            return None
        return rest[1:end]
    return rest.split(None, 1)[0]


def scan_ulb_arff(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise EvidenceError(f"dataset not found: {source}")

    started = time.perf_counter()
    file_sha = _file_sha256(source)
    columns: list[str] = []
    data_started = False
    row_count = 0
    fraud_count = 0
    legitimate_count = 0
    zero_amount_count = 0
    nonzero_amount_count = 0
    total_minor = 0
    min_nonzero_minor: int | None = None
    max_nonzero_minor: int | None = None
    first_time: str | None = None
    last_time: str | None = None
    instruction_count = 0
    malformed_count = 0
    fingerprint = hashlib.sha256()

    with source.open("r", encoding="utf-8", newline="") as fh:
        for raw_line in fh:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("%"):
                continue
            if not data_started:
                if stripped.lower() == "@data":
                    data_started = True
                    missing = [name for name in _REQUIRED_ULB_COLUMNS if name not in columns]
                    if missing:
                        raise EvidenceError(
                            "ULB dataset required columns missing: " + ", ".join(missing)
                        )
                    continue
                attribute = _parse_attribute_name(stripped)
                if attribute is not None:
                    columns.append(attribute)
                continue

            try:
                values = next(csv.reader([raw_line]))
            except csv.Error as exc:
                raise EvidenceError(f"malformed ARFF row {row_count + 1}") from exc
            if len(values) != len(columns):
                raise EvidenceError(
                    f"ARFF row {row_count + 1} has {len(values)} values for {len(columns)} columns"
                )

            row_count += 1
            row = dict(zip(columns, (value.strip() for value in values)))
            time_value = row["Time"]
            amount_text = row["Amount"]
            class_text = row["Class"]
            if class_text not in {"0", "1", "0.0", "1.0"}:
                raise EvidenceError(f"unsupported class label at row {row_count}: {class_text}")
            is_fraud = class_text in {"1", "1.0"}
            fraud_count += int(is_fraud)
            legitimate_count += int(not is_fraud)

            amount_minor = amount_to_minor_exact(amount_text)
            if amount_minor < 0:
                raise EvidenceError(f"negative amount at row {row_count}")
            total_minor += amount_minor
            if amount_minor == 0:
                zero_amount_count += 1
            else:
                nonzero_amount_count += 1
                min_nonzero_minor = (
                    amount_minor if min_nonzero_minor is None else min(min_nonzero_minor, amount_minor)
                )
                max_nonzero_minor = (
                    amount_minor if max_nonzero_minor is None else max(max_nonzero_minor, amount_minor)
                )
                build_ulb_instruction(
                    row_number=row_count,
                    time_value=time_value,
                    amount_minor=amount_minor,
                )
                instruction_count += 1

            if first_time is None:
                first_time = time_value
            last_time = time_value

            fingerprint.update(
                f"{row_count}|{time_value}|{amount_text}|{1 if is_fraud else 0}\n".encode("utf-8")
            )

    if not data_started:
        raise EvidenceError("ARFF @data section not found")

    elapsed = time.perf_counter() - started
    return {
        "dataset": {
            "source_format": "arff",
            "row_count": row_count,
            "fraud_count": fraud_count,
            "legitimate_count": legitimate_count,
            "file_sha256": file_sha,
            "row_fingerprint_sha256": fingerprint.hexdigest(),
        },
        "amounts": {
            "zero_amount_count": zero_amount_count,
            "nonzero_amount_count": nonzero_amount_count,
            "total_minor": total_minor,
            "min_nonzero_minor": min_nonzero_minor,
            "max_nonzero_minor": max_nonzero_minor,
            "currency_code_used_for_contract_validation": "XXX",
        },
        "time": {
            "first": first_time,
            "last": last_time,
        },
        "validation": {
            "switch_instruction_count": instruction_count,
            "malformed_count": malformed_count,
            "live_funds_moved": False,
            "production_authorized": False,
            "fraud_accuracy_evaluated": False,
        },
        "runtime": {
            "elapsed_seconds": elapsed,
        },
    }
