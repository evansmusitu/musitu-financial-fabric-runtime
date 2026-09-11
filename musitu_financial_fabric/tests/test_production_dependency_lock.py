from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import config


def _real_production_settings() -> config.Settings:
    return config.Settings(
        environment="production",
        metadata_db_url="postgresql://musitu:test@127.0.0.1/musitu",
        ledger_backend="tigerbeetle",
        tigerbeetle_cluster_id=1,
        tigerbeetle_addresses="127.0.0.1:3000",
        tigerbeetle_operation_timeout_seconds=5,
    )


def test_real_production_accepts_current_evidence_locked_runtime():
    cfg = _real_production_settings()
    assert cfg.is_production is True
    assert cfg.uses_postgres is True


def test_unproven_python_patch_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "sys", SimpleNamespace(version_info=(3, 12, 15)))
    with pytest.raises(ValueError, match="outside evidence-locked versions"):
        _real_production_settings()


def test_dependency_version_drift_is_rejected(monkeypatch):
    original = config.distribution_version

    def drifted(name: str) -> str:
        if name == "fastapi":
            return "999.0.0"
        return original(name)

    monkeypatch.setattr(config, "distribution_version", drifted)
    with pytest.raises(ValueError, match=r"fastapi==999\.0\.0.*expected fastapi==0\.141\.1"):
        _real_production_settings()


def test_missing_production_dependency_is_rejected(monkeypatch):
    original = config.distribution_version

    def missing(name: str) -> str:
        if name == "httpx":
            raise config.PackageNotFoundError(name)
        return original(name)

    monkeypatch.setattr(config, "distribution_version", missing)
    with pytest.raises(ValueError, match="production dependency httpx is missing"):
        _real_production_settings()


def test_non_deployment_topology_does_not_enforce_runtime_lock(monkeypatch):
    monkeypatch.setattr(config, "sys", SimpleNamespace(version_info=(9, 9, 9)))
    cfg = config.Settings(
        environment="production",
        metadata_db_url="",
        ledger_backend="tigerbeetle",
        tigerbeetle_addresses="127.0.0.1:3000",
    )
    assert cfg.uses_postgres is False
