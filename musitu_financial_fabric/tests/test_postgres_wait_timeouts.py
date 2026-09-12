from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app import db
from app.config import Settings


class _FakeRawConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _install_fake_psycopg(monkeypatch, calls: list[tuple[tuple, dict]]) -> None:
    psycopg = ModuleType("psycopg")

    def connect(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeRawConnection()

    psycopg.connect = connect
    rows = ModuleType("psycopg.rows")
    rows.dict_row = object()
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows)


def test_postgres_connection_applies_connect_statement_and_lock_deadlines(monkeypatch):
    calls: list[tuple[tuple, dict]] = []
    _install_fake_psycopg(monkeypatch, calls)
    monkeypatch.setattr(
        db,
        "settings",
        Settings(
            metadata_db_url="postgresql://db.invalid/musitu",
            metadata_db_connect_timeout_seconds=3,
            metadata_db_statement_timeout_seconds=7,
            metadata_db_lock_timeout_seconds=2,
        ),
    )

    with db.connect():
        pass

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("postgresql://db.invalid/musitu",)
    assert kwargs["connect_timeout"] == 3
    assert kwargs["options"] == "-c statement_timeout=7000 -c lock_timeout=2000"
    assert kwargs["autocommit"] is True
    assert "row_factory" in kwargs


@pytest.mark.parametrize(
    ("connect_timeout", "statement_timeout", "lock_timeout", "message"),
    [
        (0, 10, 5, "connect timeout"),
        (31, 10, 5, "connect timeout"),
        (5, 0, 5, "statement timeout"),
        (5, 61, 5, "statement timeout"),
        (5, 10, 0, "lock timeout"),
        (5, 10, 31, "lock timeout"),
        (5, 4, 5, "must not exceed"),
    ],
)
def test_postgres_wait_deadlines_fail_closed_when_out_of_bounds(
    connect_timeout: int,
    statement_timeout: int,
    lock_timeout: int,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        Settings(
            metadata_db_url="postgresql://db.invalid/musitu",
            metadata_db_connect_timeout_seconds=connect_timeout,
            metadata_db_statement_timeout_seconds=statement_timeout,
            metadata_db_lock_timeout_seconds=lock_timeout,
        )
