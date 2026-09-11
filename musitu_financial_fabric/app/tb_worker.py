from __future__ import annotations

import json
import sys

from .config import settings
from .ledger import _ledger_id, _u128


def _client():
    try:
        import tigerbeetle as tb
    except ImportError as exc:
        raise RuntimeError("TigerBeetle Python client is unavailable") from exc
    addresses = settings.tigerbeetle_addresses.strip()
    if not addresses:
        raise RuntimeError("TigerBeetle replica addresses are not configured")
    return tb, tb.ClientSync(cluster_id=settings.tigerbeetle_cluster_id, replica_addresses=addresses)


def _create_account(tb, client, payload: dict) -> dict:
    account_id = str(payload["account_id"])
    currency = str(payload["currency"]).upper()
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
    allowed = {tb.CreateAccountStatus.CREATED, tb.CreateAccountStatus.EXISTS}
    return {"ok": result.status in allowed, "failures": [] if result.status in allowed else [str(result.status)]}


def _create_transfers(tb, client, payload: dict) -> dict:
    reference = str(payload["reference"])
    journal_id = str(payload["journal_id"])
    currency = str(payload["currency"]).upper()
    legs = list(payload["legs"])
    events = []
    for index, leg in enumerate(legs):
        flags = tb.TransferFlags.LINKED if index < len(legs) - 1 else 0
        events.append(
            tb.Transfer(
                id=_u128(f"{reference}|{index}"),
                debit_account_id=_u128(str(leg[0])),
                credit_account_id=_u128(str(leg[1])),
                amount=int(leg[2]),
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
    return {"ok": not failures, "failures": failures}


def _lookup_accounts(_tb, client, payload: dict) -> dict:
    rows = client.lookup_accounts([int(value) for value in payload.get("ids", [])])
    return {
        "ok": True,
        "accounts": [
            {
                "id": int(row.id),
                "debits_posted": int(row.debits_posted),
                "credits_posted": int(row.credits_posted),
            }
            for row in rows
        ],
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        operation = str(payload.get("operation", ""))
        tb, client = _client()
        try:
            if operation == "create_account":
                response = _create_account(tb, client, payload)
            elif operation == "create_transfers":
                response = _create_transfers(tb, client, payload)
            elif operation == "lookup_accounts":
                response = _lookup_accounts(tb, client, payload)
            else:
                raise RuntimeError("unsupported TigerBeetle worker operation")
        finally:
            client.close()
        print(json.dumps(response, sort_keys=True), flush=True)
        return 0 if response.get("ok") else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}, sort_keys=True), flush=True)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
