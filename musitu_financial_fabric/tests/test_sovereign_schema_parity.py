from __future__ import annotations

from app.db import POSTGRES_SCHEMA, SQLITE_SCHEMA


PHASE2_TABLES = (
    "scheme_certification_cases",
    "scheme_certification_checks",
    "scheme_settlement_cycles",
    "scheme_clearing_obligations",
    "scheme_exceptions",
    "scheme_exception_evidence",
    "country_profile_dependencies",
)


def _create_count(schema: str, table: str) -> int:
    needle = f"CREATE TABLE IF NOT EXISTS {table} "
    return schema.count(needle)


def test_phase2_schema_tables_exist_exactly_once_in_sqlite_and_postgres():
    for table in PHASE2_TABLES:
        assert _create_count(SQLITE_SCHEMA, table) == 1, f"SQLite {table} declaration count"
        assert _create_count(POSTGRES_SCHEMA, table) == 1, f"PostgreSQL {table} declaration count"


def test_phase2_clearing_and_exception_indexes_exist_in_both_schemas():
    assert SQLITE_SCHEMA.count("ix_scheme_clearing_obligations_cycle") == 1
    assert POSTGRES_SCHEMA.count("ix_scheme_clearing_obligations_cycle") == 1
