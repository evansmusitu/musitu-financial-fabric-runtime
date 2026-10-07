from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import settings


SQLITE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS merchants (id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'sandbox',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY,owner_type TEXT NOT NULL,owner_id TEXT NOT NULL,currency TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_accounts_owner_currency_kind ON accounts(owner_type,owner_id,currency,kind);
CREATE TABLE IF NOT EXISTS journal_entries (id TEXT PRIMARY KEY,reference TEXT NOT NULL UNIQUE,memo TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ledger_postings (id INTEGER PRIMARY KEY AUTOINCREMENT,journal_id TEXT NOT NULL REFERENCES journal_entries(id),account_id TEXT NOT NULL REFERENCES accounts(id),delta_minor INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_postings_account ON ledger_postings(account_id);
CREATE TABLE IF NOT EXISTS payment_intents (id TEXT PRIMARY KEY,merchant_id TEXT NOT NULL REFERENCES merchants(id),destination_account_id TEXT NOT NULL REFERENCES accounts(id),amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,rail TEXT NOT NULL,payer_ref TEXT,description TEXT,status TEXT NOT NULL,external_reference TEXT,idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_events (event_id TEXT PRIMARY KEY,provider TEXT NOT NULL,payload_hash TEXT NOT NULL,received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (seq INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,entity_id TEXT NOT NULL,body_json TEXT NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identities (id TEXT PRIMARY KEY,kind TEXT NOT NULL,display_name TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_mandates (id TEXT PRIMARY KEY,principal_id TEXT NOT NULL REFERENCES identities(id),agent_id TEXT NOT NULL REFERENCES identities(id),max_per_payment_minor INTEGER NOT NULL,max_daily_minor INTEGER NOT NULL,currency TEXT NOT NULL,allowed_rails_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS route_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT,payment_id TEXT NOT NULL,requested_rail TEXT NOT NULL,selected_rail TEXT NOT NULL,score REAL NOT NULL,cost_bps INTEGER NOT NULL,latency_ms INTEGER NOT NULL,success_probability REAL NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_mandate_reservations (idempotency_key TEXT PRIMARY KEY,mandate_id TEXT NOT NULL REFERENCES agent_mandates(id),day_utc TEXT NOT NULL,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,payment_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_agent_mandate_reservations_daily ON agent_mandate_reservations(mandate_id,day_utc,status);
CREATE TABLE IF NOT EXISTS payment_idempotency (idempotency_key TEXT PRIMARY KEY,request_hash TEXT NOT NULL,status TEXT NOT NULL,payment_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scheme_participants (id TEXT PRIMARY KEY,name TEXT NOT NULL,participant_type TEXT NOT NULL,scheme_code TEXT NOT NULL UNIQUE,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payment_aliases (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),alias TEXT NOT NULL UNIQUE,account_ref TEXT NOT NULL,alias_type TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_payment_aliases_participant ON payment_aliases(participant_id);
CREATE TABLE IF NOT EXISTS qr_scheme_profiles (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),profile_key TEXT NOT NULL,mai_id TEXT NOT NULL,allocation_ref TEXT NOT NULL,external_verification INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,UNIQUE(profile_key,mai_id),UNIQUE(profile_key,participant_id));
CREATE TABLE IF NOT EXISTS scheme_qr_records (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),merchant_ref TEXT NOT NULL,alias TEXT NOT NULL,currency TEXT NOT NULL,amount_minor INTEGER,nonce TEXT NOT NULL UNIQUE,expires_at TEXT,profile_key TEXT NOT NULL DEFAULT 'generic',scheme_profile_id TEXT REFERENCES qr_scheme_profiles(id),channel TEXT NOT NULL DEFAULT 'pos',point_of_initiation_method TEXT NOT NULL DEFAULT '11',reference_tag_62_05 TEXT,serialization_status TEXT NOT NULL DEFAULT 'internal_reference',created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_scheme_qr_records_participant ON scheme_qr_records(participant_id);
CREATE TABLE IF NOT EXISTS request_to_pay (id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,request_hash TEXT NOT NULL,payee_alias TEXT NOT NULL,payer_alias TEXT NOT NULL,amount_minor INTEGER NOT NULL,currency TEXT NOT NULL,reference TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_request_to_pay_payer_status ON request_to_pay(payer_alias,status);
CREATE INDEX IF NOT EXISTS ix_request_to_pay_payee_status ON request_to_pay(payee_alias,status);
CREATE TABLE IF NOT EXISTS scheme_certification_cases (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),scheme_profile TEXT NOT NULL,evidence_ref TEXT NOT NULL,required_checks_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scheme_certification_checks (id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES scheme_certification_cases(id),check_key TEXT NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NOT NULL,actor TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(case_id,check_key));
CREATE TABLE IF NOT EXISTS scheme_settlement_cycles (id TEXT PRIMARY KEY,profile_key TEXT NOT NULL,cycle_ref TEXT NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,settlement_evidence_ref TEXT,external_settlement_verified BOOLEAN NOT NULL DEFAULT FALSE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(profile_key,cycle_ref));
CREATE TABLE IF NOT EXISTS scheme_clearing_obligations (id TEXT PRIMARY KEY,cycle_id TEXT NOT NULL REFERENCES scheme_settlement_cycles(id),debtor_participant_id TEXT NOT NULL REFERENCES scheme_participants(id),creditor_participant_id TEXT NOT NULL REFERENCES scheme_participants(id),amount_minor BIGINT NOT NULL,external_ref TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(cycle_id,external_ref));
CREATE INDEX IF NOT EXISTS ix_scheme_clearing_obligations_cycle ON scheme_clearing_obligations(cycle_id);
CREATE TABLE IF NOT EXISTS scheme_exceptions (id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,request_hash TEXT NOT NULL,transaction_ref TEXT NOT NULL,kind TEXT NOT NULL,claimant_participant_id TEXT NOT NULL REFERENCES scheme_participants(id),reason TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scheme_exception_evidence (id TEXT PRIMARY KEY,exception_id TEXT NOT NULL REFERENCES scheme_exceptions(id),evidence_ref TEXT NOT NULL,actor TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(exception_id,evidence_ref));
CREATE TABLE IF NOT EXISTS country_profile_dependencies (id TEXT PRIMARY KEY,profile_key TEXT NOT NULL,dependency_key TEXT NOT NULL,status TEXT NOT NULL,evidence_ref TEXT,actor TEXT NOT NULL,authorization_decision_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(profile_key,dependency_key));
CREATE TABLE IF NOT EXISTS country_profile_evidence_records (id TEXT PRIMARY KEY,profile_key TEXT NOT NULL,dependency_key TEXT NOT NULL,evidence_ref TEXT NOT NULL UNIQUE,source_authority TEXT NOT NULL,source_version TEXT NOT NULL,source_location TEXT NOT NULL,source_sha256 TEXT NOT NULL,status TEXT NOT NULL,registered_by TEXT NOT NULL,registered_at TEXT NOT NULL,verified_by TEXT,verification_authorization_decision_id TEXT,verified_at TEXT,revoked_by TEXT,revocation_authorization_decision_id TEXT,revocation_reason TEXT,revoked_at TEXT,payload_hash TEXT NOT NULL);

"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending_review',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY,owner_type TEXT NOT NULL,owner_id TEXT NOT NULL,currency TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS ux_accounts_owner_currency_kind ON accounts(owner_type,owner_id,currency,kind);
CREATE TABLE IF NOT EXISTS journal_entries (id TEXT PRIMARY KEY,reference TEXT NOT NULL UNIQUE,memo TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ledger_postings (id BIGSERIAL PRIMARY KEY,journal_id TEXT NOT NULL REFERENCES journal_entries(id),account_id TEXT NOT NULL REFERENCES accounts(id),delta_minor BIGINT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_postings_account ON ledger_postings(account_id);
CREATE TABLE IF NOT EXISTS payment_intents (id TEXT PRIMARY KEY,merchant_id TEXT NOT NULL REFERENCES merchants(id),destination_account_id TEXT NOT NULL REFERENCES accounts(id),amount_minor BIGINT NOT NULL,currency TEXT NOT NULL,rail TEXT NOT NULL,payer_ref TEXT,description TEXT,status TEXT NOT NULL,external_reference TEXT,idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_events (event_id TEXT PRIMARY KEY,provider TEXT NOT NULL,payload_hash TEXT NOT NULL,received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (seq BIGSERIAL PRIMARY KEY,event_type TEXT NOT NULL,entity_id TEXT NOT NULL,body_json TEXT NOT NULL,prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identities (id TEXT PRIMARY KEY,kind TEXT NOT NULL,display_name TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_mandates (id TEXT PRIMARY KEY,principal_id TEXT NOT NULL REFERENCES identities(id),agent_id TEXT NOT NULL REFERENCES identities(id),max_per_payment_minor BIGINT NOT NULL,max_daily_minor BIGINT NOT NULL,currency TEXT NOT NULL,allowed_rails_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS route_decisions (id BIGSERIAL PRIMARY KEY,payment_id TEXT NOT NULL,requested_rail TEXT NOT NULL,selected_rail TEXT NOT NULL,score DOUBLE PRECISION NOT NULL,cost_bps INTEGER NOT NULL,latency_ms INTEGER NOT NULL,success_probability DOUBLE PRECISION NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agent_mandate_reservations (idempotency_key TEXT PRIMARY KEY,mandate_id TEXT NOT NULL REFERENCES agent_mandates(id),day_utc TEXT NOT NULL,amount_minor BIGINT NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,payment_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_agent_mandate_reservations_daily ON agent_mandate_reservations(mandate_id,day_utc,status);
CREATE TABLE IF NOT EXISTS payment_idempotency (idempotency_key TEXT PRIMARY KEY,request_hash TEXT NOT NULL,status TEXT NOT NULL,payment_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scheme_participants (id TEXT PRIMARY KEY,name TEXT NOT NULL,participant_type TEXT NOT NULL,scheme_code TEXT NOT NULL UNIQUE,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS payment_aliases (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),alias TEXT NOT NULL UNIQUE,account_ref TEXT NOT NULL,alias_type TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_payment_aliases_participant ON payment_aliases(participant_id);
CREATE TABLE IF NOT EXISTS qr_scheme_profiles (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),profile_key TEXT NOT NULL,mai_id TEXT NOT NULL,allocation_ref TEXT NOT NULL,external_verification BOOLEAN NOT NULL DEFAULT FALSE,created_at TEXT NOT NULL,UNIQUE(profile_key,mai_id),UNIQUE(profile_key,participant_id));
CREATE TABLE IF NOT EXISTS scheme_qr_records (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),merchant_ref TEXT NOT NULL,alias TEXT NOT NULL,currency TEXT NOT NULL,amount_minor BIGINT,nonce TEXT NOT NULL UNIQUE,expires_at TEXT,profile_key TEXT NOT NULL DEFAULT 'generic',scheme_profile_id TEXT REFERENCES qr_scheme_profiles(id),channel TEXT NOT NULL DEFAULT 'pos',point_of_initiation_method TEXT NOT NULL DEFAULT '11',reference_tag_62_05 TEXT,serialization_status TEXT NOT NULL DEFAULT 'internal_reference',created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_scheme_qr_records_participant ON scheme_qr_records(participant_id);
CREATE TABLE IF NOT EXISTS request_to_pay (id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,request_hash TEXT NOT NULL,payee_alias TEXT NOT NULL,payer_alias TEXT NOT NULL,amount_minor BIGINT NOT NULL,currency TEXT NOT NULL,reference TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_request_to_pay_payer_status ON request_to_pay(payer_alias,status);
CREATE INDEX IF NOT EXISTS ix_request_to_pay_payee_status ON request_to_pay(payee_alias,status);
CREATE TABLE IF NOT EXISTS scheme_certification_cases (id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES scheme_participants(id),scheme_profile TEXT NOT NULL,evidence_ref TEXT NOT NULL,required_checks_json TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scheme_certification_checks (id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES scheme_certification_cases(id),check_key TEXT NOT NULL,result TEXT NOT NULL,evidence_ref TEXT NOT NULL,actor TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(case_id,check_key));

CREATE TABLE IF NOT EXISTS scheme_settlement_cycles (id TEXT PRIMARY KEY,profile_key TEXT NOT NULL,cycle_ref TEXT NOT NULL,currency TEXT NOT NULL,status TEXT NOT NULL,settlement_evidence_ref TEXT,external_settlement_verified BOOLEAN NOT NULL DEFAULT FALSE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(profile_key,cycle_ref));
CREATE TABLE IF NOT EXISTS scheme_clearing_obligations (id TEXT PRIMARY KEY,cycle_id TEXT NOT NULL REFERENCES scheme_settlement_cycles(id),debtor_participant_id TEXT NOT NULL REFERENCES scheme_participants(id),creditor_participant_id TEXT NOT NULL REFERENCES scheme_participants(id),amount_minor BIGINT NOT NULL,external_ref TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(cycle_id,external_ref));
CREATE INDEX IF NOT EXISTS ix_scheme_clearing_obligations_cycle ON scheme_clearing_obligations(cycle_id);
CREATE TABLE IF NOT EXISTS scheme_exceptions (id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,request_hash TEXT NOT NULL,transaction_ref TEXT NOT NULL,kind TEXT NOT NULL,claimant_participant_id TEXT NOT NULL REFERENCES scheme_participants(id),reason TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scheme_exception_evidence (id TEXT PRIMARY KEY,exception_id TEXT NOT NULL REFERENCES scheme_exceptions(id),evidence_ref TEXT NOT NULL,actor TEXT NOT NULL,payload_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(exception_id,evidence_ref));
CREATE TABLE IF NOT EXISTS country_profile_dependencies (id TEXT PRIMARY KEY,profile_key TEXT NOT NULL,dependency_key TEXT NOT NULL,status TEXT NOT NULL,evidence_ref TEXT,actor TEXT NOT NULL,authorization_decision_id TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(profile_key,dependency_key));
CREATE TABLE IF NOT EXISTS country_profile_evidence_records (id TEXT PRIMARY KEY,profile_key TEXT NOT NULL,dependency_key TEXT NOT NULL,evidence_ref TEXT NOT NULL UNIQUE,source_authority TEXT NOT NULL,source_version TEXT NOT NULL,source_location TEXT NOT NULL,source_sha256 TEXT NOT NULL,status TEXT NOT NULL,registered_by TEXT NOT NULL,registered_at TEXT NOT NULL,verified_by TEXT,verification_authorization_decision_id TEXT,verified_at TEXT,revoked_by TEXT,revocation_authorization_decision_id TEXT,revocation_reason TEXT,revoked_at TEXT,payload_hash TEXT NOT NULL);
"""


class _PostgresConnection:
    def __init__(self, conn):
        self._conn = conn

    @property
    def in_transaction(self) -> bool:
        try:
            from psycopg.pq import TransactionStatus
            return self._conn.info.transaction_status != TransactionStatus.IDLE
        except Exception:
            return False

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] | None = None):
        statement = sql.strip()
        if statement.upper() == "BEGIN IMMEDIATE":
            statement = "BEGIN"
        bound = params or ()
        normalized = " ".join(statement.split()).lower()
        if (
            "select coalesce(sum(amount_minor),0) as total" in normalized
            and "from agent_mandate_reservations" in normalized
            and len(bound) >= 1
        ):
            # SQLite's BEGIN IMMEDIATE serialized this aggregate check. PostgreSQL
            # plain BEGIN does not, so concurrent distinct idempotency keys could
            # both observe the same pre-spend total and overrun a mandate's daily
            # ceiling. Serialize only reservations for the same mandate for the
            # duration of the surrounding transaction.
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(bound[0]),),
            )
        if (
            "select * from request_to_pay where idempotency_key=" in normalized
            and len(bound) >= 1
        ):
            # SQLite BEGIN IMMEDIATE serializes the request-to-pay idempotency
            # lookup/insert sequence. Preserve equivalent per-key serialization
            # on PostgreSQL so concurrent identical keys observe one canonical
            # request instead of racing the UNIQUE constraint.
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(bound[0]),),
            )
        if (
            "select * from scheme_clearing_obligations where cycle_id=" in normalized
            and "and external_ref=" in normalized
            and len(bound) >= 2
        ):
            # Serialize clearing obligation idempotency by cycle + external
            # reference. External references may legitimately repeat in other
            # sovereign schemes or settlement cycles.
            lock_key = f"{bound[0]}:{bound[1]}"
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(lock_key),),
            )
        if (
            "select * from scheme_exceptions where idempotency_key=" in normalized
            and len(bound) >= 1
        ):
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(bound[0]),),
            )
        if (
            "select * from scheme_exception_evidence where exception_id=" in normalized
            and "and evidence_ref=" in normalized
            and len(bound) >= 2
        ):
            lock_key = f"{bound[0]}:{bound[1]}"
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(lock_key),),
            )
        if (
            "select * from country_profile_dependencies where profile_key=" in normalized
            and "and dependency_key=" in normalized
            and len(bound) >= 2
        ):
            lock_key = f"{bound[0]}:{bound[1]}"
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (str(lock_key),),
            )
        if (
            "select * from country_profile_evidence_records where evidence_ref="
            in normalized
            and len(bound) >= 1
        ):
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"evidence-ref:{bound[0]}",),
            )
        if (
            "select * from country_profile_evidence_records where id=" in normalized
            and len(bound) >= 1
        ):
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"evidence-id:{bound[0]}",),
            )
        return self._conn.execute(statement.replace("?", "%s"), bound)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self._conn.execute(statement)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


@contextmanager
def connect():
    # Actual production startup is guarded by enforce_safe_startup(), which requires
    # PostgreSQL. Allow direct unit tests to exercise production-only business rules
    # against an isolated SQLite DB without turning that into an accepted deployment.
    if settings.metadata_db_url:
        if not settings.uses_postgres:
            raise RuntimeError("configured control metadata database must be PostgreSQL")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PostgreSQL metadata storage") from exc
        conn = psycopg.connect(settings.metadata_db_url, autocommit=True, row_factory=dict_row)
        wrapper = _PostgresConnection(conn)
        try:
            yield wrapper
        finally:
            conn.close()
        return

    db_path = Path(settings.db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(POSTGRES_SCHEMA if settings.metadata_db_url else SQLITE_SCHEMA)