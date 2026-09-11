from __future__ import annotations

import subprocess

import pytest

from app import ledger
from app.config import Settings


def _production_settings(**overrides) -> Settings:
    values = dict(
        environment="production",
        metadata_db_url="postgresql://musitu:test@127.0.0.1/musitu",
        ledger_backend="tigerbeetle",
        tigerbeetle_cluster_id=1,
        tigerbeetle_addresses="127.0.0.1:3000",
        tigerbeetle_operation_timeout_seconds=5,
    )
    values.update(overrides)
    return Settings(**values)


def test_real_production_topology_uses_bounded_tigerbeetle(monkeypatch):
    monkeypatch.setattr(ledger, "settings", _production_settings())
    assert ledger._uses_bounded_production_tigerbeetle() is True


def test_sqlite_unit_topology_keeps_existing_in_process_test_seam(monkeypatch):
    monkeypatch.setattr(
        ledger,
        "settings",
        Settings(
            environment="production",
            metadata_db_url="",
            ledger_backend="tigerbeetle",
            tigerbeetle_addresses="127.0.0.1:3000",
        ),
    )
    assert ledger._uses_bounded_production_tigerbeetle() is False


def test_worker_timeout_maps_to_fail_closed_ledger_error(monkeypatch):
    cfg = _production_settings(tigerbeetle_operation_timeout_seconds=2)
    monkeypatch.setattr(ledger, "settings", cfg)

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(ledger.subprocess, "run", timed_out)
    with pytest.raises(ledger.LedgerError, match="timed out after 2 seconds"):
        ledger._tb_worker_request({"operation": "lookup_accounts", "ids": [1]})


def test_invalid_production_timeout_fails_before_worker_launch(monkeypatch):
    monkeypatch.setattr(ledger, "settings", _production_settings(tigerbeetle_operation_timeout_seconds=0))

    def must_not_run(*args, **kwargs):
        raise AssertionError("worker should not launch with an invalid production timeout")

    monkeypatch.setattr(ledger.subprocess, "run", must_not_run)
    with pytest.raises(ledger.LedgerError, match="between 1 and 30 seconds"):
        ledger._tb_worker_request({"operation": "lookup_accounts", "ids": [1]})


def test_worker_failure_is_fail_closed(monkeypatch):
    monkeypatch.setattr(ledger, "settings", _production_settings())
    completed = subprocess.CompletedProcess(
        args=["python", "-m", "app.tb_worker"],
        returncode=3,
        stdout='{"error_type":"RuntimeError","ok":false}\n',
        stderr="",
    )
    monkeypatch.setattr(ledger.subprocess, "run", lambda *args, **kwargs: completed)
    with pytest.raises(ledger.LedgerError, match="TigerBeetle worker failed: RuntimeError"):
        ledger._tb_worker_request({"operation": "lookup_accounts", "ids": [1]})
