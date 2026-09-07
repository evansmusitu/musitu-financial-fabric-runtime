from __future__ import annotations

import uuid
from typing import Iterable

from .audit import append_audit, now_iso
from .db import connect


class LedgerError(RuntimeError):
    pass


def create_account(owner_type: str, owner_id: str, currency: str, kind: str) -> dict:
    currency = currency.upper()
    account_id = f"acct_{uuid.uuid4().hex}"
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
            conn.execute(
                "INSERT INTO accounts(id,owner_type,owner_id,currency,kind,status,created_at) VALUES (?,?,?,?,?,'active',?)",
                (account_id, owner_type, owner_id, currency, kind, created_at),
            )
            append_audit("account.created", account_id, {
                "owner_type": owner_type, "owner_id": owner_id, "currency": currency, "kind": kind
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
    with connect() as conn:
        row = conn.execute("SELECT COALESCE(SUM(delta_minor),0) AS b FROM ledger_postings WHERE account_id=?", (account_id,)).fetchone()
    return int(row["b"])


def post(reference: str, memo: str, postings: Iterable[tuple[str, int]]) -> str:
    postings = list(postings)
    if len(postings) < 2:
        raise LedgerError("A journal entry requires at least two postings")
    if sum(delta for _, delta in postings) != 0:
        raise LedgerError("Unbalanced journal entry")
    journal_id = f"jrnl_{uuid.uuid4().hex}"
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute("SELECT id FROM journal_entries WHERE reference=?", (reference,)).fetchone()
            if existing:
                conn.execute("COMMIT")
                return existing["id"]
            currencies = set()
            for account_id, _ in postings:
                row = conn.execute("SELECT currency,status FROM accounts WHERE id=?", (account_id,)).fetchone()
                if not row or row["status"] != "active":
                    raise LedgerError(f"Invalid account: {account_id}")
                currencies.add(row["currency"])
            if len(currencies) != 1:
                raise LedgerError("Cross-currency journal entries are not allowed; use explicit FX legs")
            conn.execute(
                "INSERT INTO journal_entries(id,reference,memo,created_at) VALUES (?,?,?,?)",
                (journal_id, reference, memo, now_iso()),
            )
            for account_id, delta in postings:
                conn.execute(
                    "INSERT INTO ledger_postings(journal_id,account_id,delta_minor) VALUES (?,?,?)",
                    (journal_id, account_id, int(delta)),
                )
            append_audit("ledger.posted", journal_id, {
                "reference": reference,
                "memo": memo,
                "postings": [{"account_id": a, "delta_minor": d} for a, d in postings],
            }, conn=conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return journal_id
