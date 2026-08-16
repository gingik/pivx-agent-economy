-- ledger-schema.sql — canonical schema for the PIVX agent economy ledger.
-- Mirrors SCHEMA in scripts/ledger.py. Existing databases are migrated in
-- place by ledger.py (ALTER TABLE ADD COLUMN); the task_title/category/
-- verification/proof columns were added 2026-08-16 for task introspection
-- and proof metadata (improvements list items 1 & 6).

CREATE TABLE IF NOT EXISTS task_rewards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    handle          TEXT NOT NULL,
    bounty_sat      INTEGER,
    status          TEXT NOT NULL DEFAULT 'applied',
    txid            TEXT,
    reason          TEXT,
    ts              INTEGER NOT NULL,
    -- introspection (item 1): task get fields mirrored on the latest row
    task_title      TEXT,
    category        TEXT,
    verification    TEXT,
    -- proof metadata (item 6): produced by produce-proof.py / work-dispatcher.py
    deliverable_path TEXT,
    proof_type      TEXT,
    proof_hash      TEXT,
    signature       TEXT,
    signer_addr     TEXT
);

CREATE TABLE IF NOT EXISTS spend_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    direction   TEXT NOT NULL,
    amount_sat  INTEGER NOT NULL,
    txid        TEXT,
    allowed     INTEGER NOT NULL,
    reason      TEXT
);
