from __future__ import annotations

from typing import Any

from .config import settings
from .db import connect
from .ledger import _tb_client, _u128


_LOOKUP_BATCH_SIZE = 4096


def _reference_result() -> dict[str, Any]:
    return {
        "applicable": False,
        "backend": settings.ledger_backend,
        "consistent": True,
        "accounts_checked": 0,
        "missing_accounts": [],
        "mismatches": [],
    }


def reconcile_monetary_truth() -> dict[str, Any]:
    """Compare the PostgreSQL ledger mirror with TigerBeetle monetary truth.

    Production uses TigerBeetle as the authoritative monetary store while
    PostgreSQL retains the journal/account metadata needed for audit and
    operations. Reconciliation is fail-closed: any lookup error, missing
    TigerBeetle account, or balance divergence is inconsistent. An empty
    metadata mirror still performs a TigerBeetle lookup probe so a fresh
    deployment cannot claim successful reconciliation without reaching the
    authoritative ledger.
    """
    if settings.ledger_backend != "tigerbeetle":
        return _reference_result()

    try:
        with connect() as conn:
            rows = conn.execute(
                """SELECT a.id,a.currency,COALESCE(SUM(p.delta_minor),0) AS expected_balance_minor
                   FROM accounts a
                   LEFT JOIN ledger_postings p ON p.account_id=a.id
                   WHERE a.status='active'
                   GROUP BY a.id,a.currency
                   ORDER BY a.id"""
            ).fetchall()
        accounts = [
            {
                "id": str(row["id"]),
                "currency": str(row["currency"]),
                "expected_balance_minor": int(row["expected_balance_minor"]),
                "tigerbeetle_id": _u128(str(row["id"])),
            }
            for row in rows
        ]
    except Exception as exc:
        return {
            "applicable": True,
            "backend": "tigerbeetle",
            "consistent": False,
            "accounts_checked": 0,
            "missing_accounts": [],
            "mismatches": [],
            "error": f"metadata_read:{type(exc).__name__}",
        }

    client = None
    try:
        _, client = _tb_client()
        actual_by_id: dict[int, Any] = {}
        if not accounts:
            client.lookup_accounts([1])
        else:
            for start in range(0, len(accounts), _LOOKUP_BATCH_SIZE):
                ids = [row["tigerbeetle_id"] for row in accounts[start : start + _LOOKUP_BATCH_SIZE]]
                for account in client.lookup_accounts(ids):
                    actual_by_id[int(account.id)] = account
    except Exception as exc:
        return {
            "applicable": True,
            "backend": "tigerbeetle",
            "consistent": False,
            "accounts_checked": len(accounts),
            "missing_accounts": [],
            "mismatches": [],
            "error": f"tigerbeetle_lookup:{type(exc).__name__}",
        }
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    if not accounts:
        return {
            "applicable": True,
            "backend": "tigerbeetle",
            "consistent": True,
            "accounts_checked": 0,
            "missing_accounts": [],
            "mismatches": [],
        }

    missing: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for expected in accounts:
        actual = actual_by_id.get(expected["tigerbeetle_id"])
        if actual is None:
            missing.append({"account_id": expected["id"], "currency": expected["currency"]})
            continue
        actual_balance = int(actual.credits_posted) - int(actual.debits_posted)
        expected_balance = int(expected["expected_balance_minor"])
        if actual_balance != expected_balance:
            mismatches.append(
                {
                    "account_id": expected["id"],
                    "currency": expected["currency"],
                    "expected_balance_minor": expected_balance,
                    "actual_balance_minor": actual_balance,
                    "delta_minor": actual_balance - expected_balance,
                }
            )

    return {
        "applicable": True,
        "backend": "tigerbeetle",
        "consistent": not missing and not mismatches,
        "accounts_checked": len(accounts),
        "missing_accounts": missing,
        "mismatches": mismatches,
    }
