from __future__ import annotations

from app.db import _PostgresConnection


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        return object()


def test_postgres_daily_mandate_sum_takes_per_mandate_transaction_lock_first():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)
    query = """SELECT COALESCE(SUM(amount_minor),0) AS total
               FROM agent_mandate_reservations
               WHERE mandate_id=? AND day_utc=? AND status IN ('reserved','committed')"""

    conn.execute(query, ("mnd_test", "2026-09-11"))

    assert raw.calls[0] == (
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("mnd_test",),
    )
    assert raw.calls[1][0].count("%s") == 2
    assert raw.calls[1][1] == ("mnd_test", "2026-09-11")


def test_unrelated_postgres_queries_do_not_take_mandate_lock():
    raw = _FakeConnection()
    conn = _PostgresConnection(raw)

    conn.execute("SELECT * FROM merchants WHERE id=?", ("mrc_test",))

    assert raw.calls == [("SELECT * FROM merchants WHERE id=%s", ("mrc_test",))]
