from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
import zlib
from typing import Iterable

from .audit import append_audit, now_iso
from .config import settings
from .db import connect


class LedgerError(RuntimeError):
    pass


def _uses_tigerbeetle() -> bool:
    """Select the configured ledger implementation.

    Real production application startup independently enforces
    MUSITU_LEDGER_BACKEND=tigerbeetle in production.py. Keeping backend
    selection separate here lets isolated unit tests exercise production-only
    business rules without pretending that a reference-ledger process is a
    valid production deployment.
    """
    return settings.ledger_backend == "tigerbeetle"


def _uses_bounded_production_tigerbeetle() -> bool:
    return settings.is_production and settings.uses_postgres and _uses_tigerbeetle()


def _u128(text: str) -> int:
    value = int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest(), "little")
    return value or 1


def _ledger_id(currency: str) -> int:
    return (zlib.crc32(currency.upper().encode("ascii")) & 0xFFFFFFFF) or 1


def _app_account_id(owner_type: str, owner_id: str, currency: str, kind: str) -> str:
    digest = hashlib.sha256(f"{owner_type}|{owner_id}|{currency.upper()}|{kind}".encode()).hexdigest()[:32]
    return f"acct_{digest}"


def _tb_client():
    try:
        import tigerbeetle as tb
    except ImportError as exc:
        raise LedgerError("TigerBeetle Python client is required when the TigerBeetle ledger backend is configured") from exc
    addresses = settings.tigerbeetle_addresses.strip()
    if not addresses:
        raise LedgerError("TigerBeetle replica addresses are not configured")
    return tb, tb.ClientSync(cluster_id=settings.tigerbeetle_cluster_id, replica_addresses=addresses)


def _tb_worker_request(payload: dict) -> dict:
    timeout_seconds = int(settings.tigerbeetle_operation_timeout_seconds)
    if not 1 <= timeout_seconds <= 30:
        raise LedgerError("TigerBeetle production operation timeout must be between 1 and 30 seconds")
    env = os.environ.copy()
    env.update(
        {
            "MUSITU_ENV": settings.environment,
            "MUSITU_METADATA_DB_URL": settings.metadata_db_url,
            "MUSITU_LEDGER_BACKEND": settings.ledger_backend,
            "MUSITU_TIGERBEETLE_CLUSTER_ID": str(settings.tigerbeetle_cluster_id),
            "MUSITU_TIGERBEETLE_ADDRESSES": settings.tigerbeetle_addresses,
            "MUSITU_TIGERBEETLE_OPERATION_TIMEOUT_SECONDS": str(timeout_seconds),
            "MUSITU_TIGERBEETLE_ACCOUNT_CODE": str(settings.tigerbeetle_account_code),
            "MUSITU_TIGERBEETLE_TRANSFER_CODE": str(settings.tigerbeetle_transfer_code),
        }
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.tb_worker"],
            input=json.dumps(payload, separators=(",", ":")),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise LedgerError(f"TigerBeetle operation timed out after {timeout_seconds} seconds") from exc
    try:
        response = json.loads(completed.stdout.strip()) if completed.stdout.strip() else {}
    except Exception as exc:
        raise LedgerError("TigerBeetle worker returned an invalid response") from exc
    if completed.returncode != 0 or not response.get("ok"):
        error_type = str(response.get("error_type") or "request_failed")
        failures = response.get("failures") or []
        detail = ",".join(str(value) for value in failures) if failures else error_type
        raise LedgerError(f"TigerBeetle worker failed: {detail}")
    return response


def create_account(owner_type: str, owner_id: str, currency: str, kind: str) -> dict:
    currency = currency.upper()
    account_id = _app_account_id(owner_type, owner_id, currency, kind) if _uses_tigerbeetle() else f"acct_{uuid.uuid4().hex}"
    created_at = now_iso()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT * FROM accounts WHERE owner_type=? AND owner_id=? AND currency=? AND kind=?",
                (owner_type, owner_id, currency, kind),
            ).fetchone()
            if existing:
                conn.execute("COMMIT")
                return dict(existing)

            if _uses_tigerbeetle():
                if _uses_bounded_production_tigerbeetle():
                    _tb_worker_request(
                        {
                            "operation": "create_account",
                            "account_id": account_id,
                            "currency": currency,
                        }
                    )
                else:
                    tb, client = _tb_client()
                    try:
                        event = tb.Account(
                            id=_u128(account_id),
                            debits_pending=0,
                            debits_posted=0,
                            credits_pending=0,
                            credits_posted=0,
                            user_data_128=0,
                            user_data_64=0,
                            user_data_32=0,
                            ledger=_ledger_id(currency),
                            code=settings.tigerbeetle_account_code,
                            flags=0,
                            timestamp=0,
                        )
                        result = client.create_accounts([event])[0]
                        if result.status not in {tb.CreateAccountStatus.CREATED, tb.CreateAccountStatus.EXISTS}:
                            raise LedgerError(f"TigerBeetle account creation failed: {result.status}")
                    finally:
                        client.close()

            conn.execute(
                "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,'active',?)",
                (account_id, owner_type, owner_id, currency, kind, created_at),
            )
            append_audit(
                "account.created",
                account_id,
                {
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "currency": currency,
                    "kind": kind,
                    "monetary_backend": "tigerbeetle" if _uses_tigerbeetle() else "reference",
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {
        "id": account_id,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "currency": currency,
        "kind": kind,
        "status": "active",
        "created_at": created_at,
    }


def get_account(account_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return dict(row) if row else None


def balance(account_id: str) -> int:
    if _uses_tigerbeetle():
        account = get_account(account_id)
        if not account:
            raise LedgerError(f"Invalid account: {account_id}")
        if _uses_bounded_production_tigerbeetle():
            response = _tb_worker_request({"operation": "lookup_accounts", "ids": [_u128(account_id)]})
            rows = response.get("accounts") or []
        else:
            _, client = _tb_client()
            try:
                raw_rows = client.lookup_accounts([_u128(account_id)])
                rows = [
                    {
                        "id": int(row.id),
                        "debits_posted": int(row.debits_posted),
                        "credits_posted": int(row.credits_posted),
                    }
                    for row in raw_rows
                ]
            finally:
                client.close()
        if len(rows) != 1:
            raise LedgerError("TigerBeetle account missing")
        row = rows[0]
        return int(row["credits_posted"]) - int(row["debits_posted"])

    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(delta_minor),0) AS b FROM ledger_postings WHERE account_id=?",
            (account_id,),
        ).fetchone()
    return int(row["b"])


def _transfer_legs(postings: list[tuple[str, int]]) -> list[tuple[str, str, int]]:
    debits = [[account_id, -int(delta)] for account_id, delta in postings if int(delta) < 0]
    credits = [[account_id, int(delta)] for account_id, delta in postings if int(delta) > 0]
    legs: list[tuple[str, str, int]] = []
    di = ci = 0
    while di < len(debits) and ci < len(credits):
        amount = min(debits[di][1], credits[ci][1])
        if amount <= 0:
            raise LedgerError("invalid zero transfer leg")
        legs.append((str(debits[di][0]), str(credits[ci][0]), int(amount)))
        debits[di][1] -= amount
        credits[ci][1] -= amount
        if debits[di][1] == 0:
            di += 1
        if credits[ci][1] == 0:
            ci += 1
    if di != len(debits) or ci != len(credits):
        raise LedgerError("could not decompose balanced journal")
    return legs


def post(reference: str, memo: str, postings: Iterable[tuple[str, int]]) -> str:
    postings = [(account_id, int(delta)) for account_id, delta in postings]
    if len(postings) < 2:
        raise LedgerError("A journal entry requires at least two postings")
    if sum(delta for _, delta in postings) != 0:
        raise LedgerError("Unbalanced journal entry")
    if any(delta == 0 for _, delta in postings):
        raise LedgerError("Zero-value postings are not allowed")

    journal_id = (
        f"jrnl_{hashlib.sha256(reference.encode()).hexdigest()[:32]}"
        if _uses_tigerbeetle()
        else f"jrnl_{uuid.uuid4().hex}"
    )
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute("SELECT id FROM journal_entries WHERE reference=?", (reference,)).fetchone()
            if existing:
                conn.execute("COMMIT")
                return existing["id"]

            currencies: set[str] = set()
            for account_id, _ in postings:
                row = conn.execute("SELECT currency,status FROM accounts WHERE id=?", (account_id,)).fetchone()
                if not row or row["status"] != "active":
                    raise LedgerError(f"Invalid account: {account_id}")
                currencies.add(row["currency"])
            if len(currencies) != 1:
                raise LedgerError("Cross-currency journal entries are not allowed; use explicit FX legs")
            currency = next(iter(currencies))

            if _uses_tigerbeetle():
                legs = _transfer_legs(postings)
                if _uses_bounded_production_tigerbeetle():
                    _tb_worker_request(
                        {
                            "operation": "create_transfers",
                            "reference": reference,
                            "journal_id": journal_id,
                            "currency": currency,
                            "legs": legs,
                        }
                    )
                else:
                    tb, client = _tb_client()
                    try:
                        events = []
                        for index, (debit_id, credit_id, amount) in enumerate(legs):
                            flags = tb.TransferFlags.LINKED if index < len(legs) - 1 else 0
                            events.append(
                                tb.Transfer(
                                    id=_u128(f"{reference}|{index}"),
                                    debit_account_id=_u128(debit_id),
                                    credit_account_id=_u128(credit_id),
                                    amount=amount,
                                    pending_id=0,
                                    user_data_128=_u128(journal_id),
                                    user_data_64=0,
                                    user_data_32=0,
                                    timeout=0,
                                    ledger=_ledger_id(currency),
                                    code=settings.tigerbeetle_transfer_code,
                                    flags=flags,
                                    timestamp=0,
                                )
                            )
                        results = client.create_transfers(events)
                        allowed = {tb.CreateTransferStatus.CREATED, tb.CreateTransferStatus.EXISTS}
                        failures = [str(result.status) for result in results if result.status not in allowed]
                        if failures:
                            raise LedgerError("TigerBeetle transfer rejected: " + ",".join(failures))
                    finally:
                        client.close()

            conn.execute(
                "INSERT INTO journal_entries(id,reference,memo,created_at) VALUES (?,?,?,?)",
                (journal_id, reference, memo, now_iso()),
            )
            for account_id, delta in postings:
                conn.execute(
                    "INSERT INTO ledger_postings(journal_id,account_id,delta_minor) VALUES (?,?,?)",
                    (journal_id, account_id, delta),
                )
            append_audit(
                "ledger.posted",
                journal_id,
                {
                    "reference": reference,
                    "memo": memo,
                    "postings": [{"account_id": a, "delta_minor": d} for a, d in postings],
                    "monetary_backend": "tigerbeetle" if _uses_tigerbeetle() else "reference",
                },
                conn=conn,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return journal_id
