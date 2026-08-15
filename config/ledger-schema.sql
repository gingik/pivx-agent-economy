-- ledger-schema.sql — SQLite ledger for the agent economy.
-- One file beside wallet data: ~/.local/share/pivx-agent-kit/ledger.db
-- Amounts in satoshis (INTEGER). No PII beyond payer addresses.
-- Memo annotation unavailable on transparent channel (shield-to-shield only) — noted.

PRAGMA foreign_keys = ON;

-- M2: merchant orders (alert-as-a-service)
CREATE TABLE IF NOT EXISTS orders (
    id           TEXT PRIMARY KEY,      -- merchant-kit invoice UUID
    external_id  TEXT UNIQUE,           -- alert-order-id (idempotency key)
    invoice_id   TEXT,
    amount_sat   INTEGER NOT NULL,
    payer_addr   TEXT,                  -- transparent payer address
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|confirmed|expired|cancelled
    txid         TEXT,
    alert_hash   TEXT,                  -- SHA256 of delivered alert payload
    signature    TEXT,                  -- sign-message base64 sig (buyer verifies)
    created_at   INTEGER NOT NULL,
    confirmed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_external ON orders(external_id);

-- M1: PIVX Tasks bounty rewards
CREATE TABLE IF NOT EXISTS task_rewards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    handle      TEXT NOT NULL,          -- worker handle (agent name)
    bounty_sat  INTEGER,
    status      TEXT NOT NULL DEFAULT 'applied',   -- applied|submitted|approved|rejected|paid|disputed
    txid        TEXT,
    reason      TEXT,                   -- rejection/dispute reason
    ts          INTEGER NOT NULL        -- epoch seconds
);
CREATE INDEX IF NOT EXISTS idx_rewards_task ON task_rewards(task_id);

-- M3: spend limits enforcement journal
CREATE TABLE IF NOT EXISTS spend_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent       TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    direction   TEXT NOT NULL,          -- out
    amount_sat  INTEGER NOT NULL,
    txid        TEXT,
    allowed     INTEGER NOT NULL,       -- 1 allowed, 0 denied
    reason      TEXT
);
