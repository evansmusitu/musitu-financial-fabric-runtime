from __future__ import annotations

import hashlib
import uuid
import zlib
from typing import Iterable

from .audit import append_audit, now_iso
from .config import settings
from .db import connect


class LedgerError(RuntimeError):
    pass


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
        raise LedgerError("TigerBeetle Python client is required in production") from exc
    addresses = [value.strip() for value in settings.tigerbeetle_addresses.split(",") if value.strip()]
    if not addresses:
        raise LedgerError("TigerBeetle replica addresses are not configured")
    return tb, tb.ClientSync(cluster_id=settings.tigerbeetle_cluster_id, replica_addresses=addresses)


def create_account(owner_type: str, owner_id: str, currency: str, kind: str) -> dict:
    currency = currency.upper()
    account_id = _app_account_id(owner_type, owner_id, currency, kind) if settings.is_production else f"acct_{uuid.uuid4().hex}"
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

            if settings.is_production:
                if settings.ledger_backend != "tigerbeetle":
                    raise LedgerError("production monetary truth must use TigerBeetle")
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
            append_audit("account.created", account_id, {
                "owner_type": owner_type, "owner_id": owner_id, "currency": currency, "kind": kind,
                "monetary_backend": "tigerbeetle" if settings.is_production else "reference",
            }, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"id": account_id, "owner_type": owner_type, "owner_id": owner_id, "currency": currency, "kind": kind, "status": "active", "created_at": created_at}


def get_account(account_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return dict(row) if row else None


def balance(account_id: str) -> int:
    if settings.is_production:
        if settings.ledger_backend != "tigerbeetle":
            raise LedgerError("production monetary truth must use TigerBeetle")
        account = get_account(account_id)
        if not account:
            raise LedgerError(f"Invalid account: {account_id}")
        tb, client = _tb_client()
        try:
            rows = client.lookup_accounts([_u128(account_id)])
        finally:
            client.close()
        if len(rows) != 1:
            raise LedgerError("TigerBeetle account missing")
        row = rows[0]
        return int(row.credits_posted) - int(row.debits_posted)

    with connect() as conn:
        row = conn.execute("SELECT COALESCE(SUM(delta_minor),0) AS b FROM ledger_postings WHERE account_id=?", (account_id,)).fetchone()
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

    journal_id = f"jrnl_{hashlib.sha256(reference.encode()).hexdigest()[:32]}" if settings.is_production else f"jrnl_{uuid.uuid4().hex}"
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

            if settings.is_production:
                if settings.ledger_backend != "tigerbeetle":
                    raise LedgerError("reference ledger is forbidden in production")
                tb, client = _tb_client()
                try:
                    legs = _transfer_legs(postings)
                    events = []
                    for index, (debit_id, credit_id, amount) in enumerate(legs):
                        flags = tb.TransferFlags.LINKED if index < len(legs) - 1 else 0
                        events.append(tb.Transfer(
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
                        ))
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
            append_audit("ledger.posted", journal_id, {
                "reference": reference,
                "memo": memo,
                "postings": [{"account_id": a, "delta_minor": d} for a, d in postings],
                "monetary_backend": "tigerbeetle" if settings.is_production else "reference",
            }, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return journal_id
