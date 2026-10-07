from __future__ import annotations

import csv
import hashlib
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .audit import verify_audit_chain
from .db import connect
from .sovereign import (
    SovereignError,
    calculate_net_positions,
    create_scheme_exception,
    create_scheme_participant,
    open_settlement_cycle,
    record_clearing_obligation,
)
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


def _iter_ulb_rows(path: str | Path):
    source = Path(path)
    columns: list[str] = []
    data_started = False
    row_number = 0
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

            values = next(csv.reader([raw_line]))
            if len(values) != len(columns):
                raise EvidenceError(
                    f"ARFF row {row_number + 1} has {len(values)} values for {len(columns)} columns"
                )
            row_number += 1
            row = dict(zip(columns, (value.strip() for value in values)))
            class_text = row["Class"]
            if class_text not in {"0", "1", "0.0", "1.0"}:
                raise EvidenceError(f"unsupported class label at row {row_number}: {class_text}")
            amount_minor = amount_to_minor_exact(row["Amount"])
            if amount_minor < 0:
                raise EvidenceError(f"negative amount at row {row_number}")
            yield {
                "row_number": row_number,
                "time": row["Time"],
                "amount_minor": amount_minor,
                "is_fraud": class_text in {"1", "1.0"},
            }

    if not data_started:
        raise EvidenceError("ARFF @data section not found")


def replay_ulb_state(
    path: str | Path,
    *,
    start_row: int = 1,
    limit: int | None = None,
) -> dict:
    start_row = int(start_row)
    if start_row <= 0:
        raise EvidenceError("replay start row must be positive")
    if limit is not None and int(limit) <= 0:
        raise EvidenceError("replay limit must be positive")
    limit = int(limit) if limit is not None else None

    suffix = hashlib.sha256(f"{Path(path)}:{time.time_ns()}".encode("utf-8")).hexdigest()[:12]
    payer = create_scheme_participant("ULB Replay Payer", "bank", f"ULBP{suffix}".upper())
    payee = create_scheme_participant("ULB Replay Payee", "psp", f"ULBM{suffix}".upper())
    cycle = open_settlement_cycle("real-dataset-ulb-2013", f"ulb-cycle-{suffix}", "XXX")

    source_rows_processed = 0
    obligations_recorded = 0
    zero_amount_rows_skipped = 0
    fraud_labels_observed = 0
    disputes_created = 0
    identical_replay_same_id = False
    conflicting_replay_failed_closed = False
    first_obligation: dict | None = None
    source_end_row: int | None = None

    for row in _iter_ulb_rows(path):
        if int(row["row_number"]) < start_row:
            continue
        if limit is not None and source_rows_processed >= limit:
            break
        source_rows_processed += 1
        source_end_row = int(row["row_number"])
        amount_minor = int(row["amount_minor"])
        external_ref = f"ulb-2013:row:{row['row_number']}"

        if row["is_fraud"]:
            fraud_labels_observed += 1
            create_scheme_exception(
                external_ref,
                "dispute",
                payee["id"],
                "real-dataset-ground-truth-fraud-label",
                f"ulb-dispute:{row['row_number']}:{suffix}",
            )
            disputes_created += 1

        if amount_minor == 0:
            zero_amount_rows_skipped += 1
            continue

        if row["row_number"] % 2:
            debtor_id, creditor_id = payer["id"], payee["id"]
        else:
            debtor_id, creditor_id = payee["id"], payer["id"]

        obligation = record_clearing_obligation(
            cycle["id"],
            debtor_id,
            creditor_id,
            amount_minor,
            external_ref,
        )
        obligations_recorded += 1

        if first_obligation is None:
            first_obligation = obligation
            replayed = record_clearing_obligation(
                cycle["id"],
                debtor_id,
                creditor_id,
                amount_minor,
                external_ref,
            )
            identical_replay_same_id = replayed["id"] == obligation["id"]
            try:
                record_clearing_obligation(
                    cycle["id"],
                    debtor_id,
                    creditor_id,
                    amount_minor + 1,
                    external_ref,
                )
            except SovereignError:
                conflicting_replay_failed_closed = True

    net_positions = calculate_net_positions(cycle["id"])
    audit_valid, audit_events, audit_broken_at = verify_audit_chain()
    with connect() as conn:
        payment_intents = int(
            conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"]
        )
        ledger_postings = int(
            conn.execute("SELECT COUNT(*) AS n FROM ledger_postings").fetchone()["n"]
        )

    return {
        "source_start_row": start_row,
        "source_end_row": source_end_row,
        "source_rows_processed": source_rows_processed,
        "obligations_recorded": obligations_recorded,
        "zero_amount_rows_skipped": zero_amount_rows_skipped,
        "fraud_labels_observed": fraud_labels_observed,
        "reference_disputes_created": disputes_created,
        "idempotency": {
            "identical_replay_same_id": identical_replay_same_id,
            "conflicting_replay_failed_closed": conflicting_replay_failed_closed,
        },
        "net_positions": net_positions,
        "audit": {
            "valid": audit_valid,
            "events": audit_events,
            "broken_at": audit_broken_at,
        },
        "side_effects": {
            "payment_intents": payment_intents,
            "ledger_postings": ledger_postings,
        },
        "synthetic_fields": {
            "participant_identity": True,
            "routing_direction": True,
        },
        "real_fields": {
            "amounts": True,
            "time_order": True,
            "fraud_labels": True,
        },
        "fraud_accuracy_evaluated": False,
        "live_funds_moved": False,
        "production_authorized": False,
    }



_ELLIPTIC_FEATURES = "elliptic_txs_features.csv"
_ELLIPTIC_CLASSES = "elliptic_txs_classes.csv"
_ELLIPTIC_EDGES = "elliptic_txs_edgelist.csv"


def _elliptic_dataset_dir(root: str | Path) -> Path:
    root_path = Path(root)
    nested = root_path / "elliptic_bitcoin_dataset"
    candidates = (nested, root_path)
    for candidate in candidates:
        if all((candidate / name).is_file() for name in (_ELLIPTIC_FEATURES, _ELLIPTIC_CLASSES, _ELLIPTIC_EDGES)):
            return candidate
    raise EvidenceError("Elliptic dataset files not found")


def _elliptic_label(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "1":
        return "illicit"
    if normalized == "2":
        return "licit"
    if normalized == "unknown":
        return "unknown"
    raise EvidenceError(f"unsupported Elliptic class label: {value}")


def scan_elliptic_dataset(root: str | Path) -> dict:
    data_dir = _elliptic_dataset_dir(root)
    features_path = data_dir / _ELLIPTIC_FEATURES
    classes_path = data_dir / _ELLIPTIC_CLASSES
    edges_path = data_dir / _ELLIPTIC_EDGES

    file_hashes = {
        "features": _file_sha256(features_path),
        "classes": _file_sha256(classes_path),
        "edges": _file_sha256(edges_path),
    }
    fingerprint = hashlib.sha256()
    for key in ("features", "classes", "edges"):
        fingerprint.update(f"{key}:{file_hashes[key]}\n".encode("utf-8"))

    node_ids: set[str] = set()
    min_time_step: int | None = None
    max_time_step: int | None = None
    with features_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for row_number, row in enumerate(reader, start=1):
            if len(row) < 2:
                raise EvidenceError(f"Elliptic feature row {row_number} is malformed")
            tx_id = str(row[0]).strip()
            if not tx_id:
                raise EvidenceError(f"Elliptic feature row {row_number} has empty transaction id")
            if tx_id in node_ids:
                raise EvidenceError(f"duplicate Elliptic transaction id: {tx_id}")
            try:
                time_step = int(str(row[1]).strip())
            except ValueError as exc:
                raise EvidenceError(f"invalid Elliptic time step at row {row_number}") from exc
            node_ids.add(tx_id)
            min_time_step = time_step if min_time_step is None else min(min_time_step, time_step)
            max_time_step = time_step if max_time_step is None else max(max_time_step, time_step)

    labels = {"illicit": 0, "licit": 0, "unknown": 0}
    labeled_ids: set[str] = set()
    with classes_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "txId" not in reader.fieldnames or "class" not in reader.fieldnames:
            raise EvidenceError("Elliptic classes required columns missing")
        for row in reader:
            tx_id = str(row.get("txId") or "").strip()
            if tx_id not in node_ids:
                raise EvidenceError(f"Elliptic class references unknown transaction: {tx_id}")
            if tx_id in labeled_ids:
                raise EvidenceError(f"duplicate Elliptic class row: {tx_id}")
            labeled_ids.add(tx_id)
            labels[_elliptic_label(str(row.get("class") or ""))] += 1

    unlabeled_nodes = node_ids - labeled_ids
    if unlabeled_nodes:
        raise EvidenceError(f"Elliptic transactions missing class rows: {len(unlabeled_nodes)}")

    edge_count = 0
    missing_endpoint_count = 0
    with edges_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "txId1" not in reader.fieldnames or "txId2" not in reader.fieldnames:
            raise EvidenceError("Elliptic edge required columns missing")
        for row_number, row in enumerate(reader, start=1):
            source = str(row.get("txId1") or "").strip()
            target = str(row.get("txId2") or "").strip()
            edge_count += 1
            if source not in node_ids or target not in node_ids:
                missing_endpoint_count += 1
                raise EvidenceError(
                    f"Elliptic edge endpoint references unknown transaction at edge {row_number}"
                )

    return {
        "graph": {
            "node_count": len(node_ids),
            "edge_count": edge_count,
            "missing_edge_endpoint_count": missing_endpoint_count,
        },
        "labels": labels,
        "time_steps": {
            "min": min_time_step,
            "max": max_time_step,
        },
        "files": file_hashes,
        "dataset_fingerprint_sha256": fingerprint.hexdigest(),
        "validation": {
            "graph_integrity": missing_endpoint_count == 0,
            "monetary_values_used": False,
            "fraud_accuracy_evaluated": False,
            "live_funds_moved": False,
            "production_authorized": False,
        },
    }


def replay_elliptic_illicit_exceptions(root: str | Path) -> dict:
    data_dir = _elliptic_dataset_dir(root)
    scan = scan_elliptic_dataset(data_dir)
    suffix = hashlib.sha256(f"{data_dir}:{time.time_ns()}".encode("utf-8")).hexdigest()[:12]
    claimant = create_scheme_participant(
        "Elliptic Reference Claimant",
        "psp",
        f"ELLC{suffix}".upper(),
    )

    illicit_labels_observed = 0
    disputes_created = 0
    identical_replay_same_id = False
    conflicting_replay_failed_closed = False
    first_tx_id: str | None = None
    first_exception: dict | None = None

    classes_path = data_dir / _ELLIPTIC_CLASSES
    with classes_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            tx_id = str(row.get("txId") or "").strip()
            label = _elliptic_label(str(row.get("class") or ""))
            if label != "illicit":
                continue
            illicit_labels_observed += 1
            idempotency_key = f"elliptic-dispute:{tx_id}:{suffix}"
            created = create_scheme_exception(
                f"elliptic-tx:{tx_id}",
                "dispute",
                claimant["id"],
                "real-dataset-elliptic-illicit-label",
                idempotency_key,
            )
            disputes_created += 1
            if first_tx_id is None:
                first_tx_id = tx_id
                first_exception = created
                replayed = create_scheme_exception(
                    f"elliptic-tx:{tx_id}",
                    "dispute",
                    claimant["id"],
                    "real-dataset-elliptic-illicit-label",
                    idempotency_key,
                )
                identical_replay_same_id = replayed["id"] == created["id"]
                try:
                    create_scheme_exception(
                        f"elliptic-tx:{tx_id}",
                        "dispute",
                        claimant["id"],
                        "conflicting-reference-reason",
                        idempotency_key,
                    )
                except SovereignError:
                    conflicting_replay_failed_closed = True

    audit_valid, audit_events, audit_broken_at = verify_audit_chain()
    with connect() as conn:
        payment_intents = int(
            conn.execute("SELECT COUNT(*) AS n FROM payment_intents").fetchone()["n"]
        )
        ledger_postings = int(
            conn.execute("SELECT COUNT(*) AS n FROM ledger_postings").fetchone()["n"]
        )

    return {
        "transactions_scanned": scan["graph"]["node_count"],
        "edges_scanned": scan["graph"]["edge_count"],
        "illicit_labels_observed": illicit_labels_observed,
        "reference_disputes_created": disputes_created,
        "idempotency": {
            "identical_replay_same_id": identical_replay_same_id,
            "conflicting_replay_failed_closed": conflicting_replay_failed_closed,
        },
        "audit": {
            "valid": audit_valid,
            "events": audit_events,
            "broken_at": audit_broken_at,
        },
        "side_effects": {
            "payment_intents": payment_intents,
            "ledger_postings": ledger_postings,
        },
        "monetary_values_used": False,
        "fraud_accuracy_evaluated": False,
        "live_funds_moved": False,
        "production_authorized": False,
    }
