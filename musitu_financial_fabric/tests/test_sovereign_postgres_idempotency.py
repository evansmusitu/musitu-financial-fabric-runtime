from __future__ import annotations

from app.db import _PostgresConnection


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return object()


def test_request_to_pay_idempotency_lookup_takes_per_key_transaction_lock_first():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)
    query = "SELECT * FROM request_to_pay WHERE idempotency_key=?"

    conn.execute(query, ("rtp-idem-1",))

    assert raw.calls[0] == (
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("rtp-idem-1",),
    )
    assert raw.calls[1] == (
        "SELECT * FROM request_to_pay WHERE idempotency_key=%s",
        ("rtp-idem-1",),
    )


def test_unrelated_postgres_query_does_not_take_sovereign_idempotency_lock():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)

    conn.execute("SELECT * FROM scheme_participants WHERE id=?", ("spn-test",))

    assert raw.calls == [
        ("SELECT * FROM scheme_participants WHERE id=%s", ("spn-test",))
    ]
