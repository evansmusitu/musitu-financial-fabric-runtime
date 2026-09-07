import importlib
from concurrent.futures import ThreadPoolExecutor


def _reload_for_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSITU_DB_PATH", str(tmp_path / "fabric.db"))
    monkeypatch.setenv("MUSITU_ENV", "sandbox")
    import app.config as config
    import app.db as db
    import app.audit as audit
    import app.ledger as ledger
    import app.service as service
    for mod in (config, db, audit, ledger, service):
        importlib.reload(mod)
    db.init_db()
    return audit, service


def test_concurrent_audit_writers_preserve_single_hash_chain(tmp_path, monkeypatch):
    audit, service = _reload_for_db(tmp_path, monkeypatch)

    with ThreadPoolExecutor(max_workers=16) as pool:
        identities = list(pool.map(lambda i: service.create_identity("human", f"User {i}"), range(80)))

    assert len(identities) == 80
    valid, count, broken_at = audit.verify_audit_chain()
    assert valid is True, f"audit chain broke at {broken_at}"
    assert count == 80
    assert broken_at is None
