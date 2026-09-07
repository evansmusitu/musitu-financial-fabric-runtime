from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS merchants (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'sandbox',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  owner_type TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_accounts_owner_currency_kind
ON accounts(owner_type, owner_id, currency, kind);

CREATE TABLE IF NOT EXISTS journal_entries (
  id TEXT PRIMARY KEY,
  reference TEXT NOT NULL UNIQUE,
  memo TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_postings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  journal_id TEXT NOT NULL REFERENCES journal_entries(id),
  account_id TEXT NOT NULL REFERENCES accounts(id),
  delta_minor INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_postings_account ON ledger_postings(account_id);

CREATE TABLE IF NOT EXISTS payment_intents (
  id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL REFERENCES merchants(id),
  destination_account_id TEXT NOT NULL REFERENCES accounts(id),
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  rail TEXT NOT NULL,
  payer_ref TEXT,
  description TEXT,
  status TEXT NOT NULL,
  external_reference TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  body_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL,
  event_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
"""


@contextmanager
def connect():
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
        conn.executescript(SCHEMA)

# MUSITU Financial Fabric v0.2 domain extensions. These remain metadata/control-plane
# records; monetary truth migrates to TigerBeetle when its mandatory runtime gate is green.
SCHEMA += """
CREATE TABLE IF NOT EXISTS identities (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_mandates (
  id TEXT PRIMARY KEY,
  principal_id TEXT NOT NULL REFERENCES identities(id),
  agent_id TEXT NOT NULL REFERENCES identities(id),
  max_per_payment_minor INTEGER NOT NULL,
  max_daily_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  allowed_rails_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS route_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id TEXT NOT NULL,
  requested_rail TEXT NOT NULL,
  selected_rail TEXT NOT NULL,
  score REAL NOT NULL,
  cost_bps INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL,
  success_probability REAL NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_mandate_reservations (
  idempotency_key TEXT PRIMARY KEY,
  mandate_id TEXT NOT NULL REFERENCES agent_mandates(id),
  day_utc TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  status TEXT NOT NULL,
  payment_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_mandate_reservations_daily
ON agent_mandate_reservations(mandate_id, day_utc, status);

CREATE TABLE IF NOT EXISTS payment_idempotency (
  idempotency_key TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  payment_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""
