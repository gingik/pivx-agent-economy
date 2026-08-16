#!/usr/bin/env python3
"""ledger.py — shared SQLite ledger access for the PIVX agent economy scripts.

Replaces the inline `python3 - <<'PYEOF'` heredocs that used to live in
task-runner.sh and enforce-limits.sh (repo rule: no heredocs, file-based
scripting only).

Subcommands:
  init-schema <db>                       create task_rewards + spend_events if missing
  journal-task <db> <agent> <task_id> <status> [reason] [ts]
  journal-introspect <db> <agent> <task_id> <title> <category> <verification>
                                         UPDATE latest row with introspected task fields
  journal-proof <db> <agent> <task_id> <deliverable_path> <proof_type> <proof_hash> <signature> <signer_addr>
                                         UPDATE latest row with proof metadata
  latest <db> <agent> <task_id>          print latest row as JSON (status watcher)
  count-signed-up <db> <agent>           gate metric: rows with REAL signup progress
  journal-spend <db> <agent> <ts> <amount_sat> <outcome>
  spent-today <db> <now>                 sum of allowed out-spend in last 24 h

Schema migration: existing databases get the proof/introspection columns
(added 2026-08-16) via ALTER TABLE — task_rewards is upgraded in place.

Stdlib only.
"""
import json
import sqlite3
import sys
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_rewards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    handle          TEXT NOT NULL,
    bounty_sat      INTEGER,
    status          TEXT NOT NULL DEFAULT 'applied',
    txid            TEXT,
    reason          TEXT,
    ts              INTEGER NOT NULL,
    task_title      TEXT,
    category        TEXT,
    verification    TEXT,
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
"""

# Columns added after the original schema (2026-08-16). task_rewards rows that
# predate them get NULLs; migrations below ALTER TABLE them into existing DBs.
TASK_REWARDS_COLUMNS = (
    "task_title TEXT", "category TEXT", "verification TEXT",
    "deliverable_path TEXT", "proof_type TEXT", "proof_hash TEXT",
    "signature TEXT", "signer_addr TEXT",
)

# Statuses that mean the agent actually progressed past the gate. 'applied'
# and 'pending-approval' rows are pre-inserted before anything real happens
# and MUST NOT open the gate (bug list #6).
REAL_SIGNUP_STATUSES = ("signed-up", "submitted", "approved", "paid", "disputed")


def conn_for(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Add post-original-schema columns to task_rewards in place."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(task_rewards)")}
    for col_def in TASK_REWARDS_COLUMNS:
        name = col_def.split()[0]
        if name not in have:
            conn.execute(f"ALTER TABLE task_rewards ADD COLUMN {col_def}")
    conn.commit()


def latest_row(conn: sqlite3.Connection, task: str, agent: str):
    return conn.execute(
        "SELECT * FROM task_rewards WHERE task_id=? AND handle=? "
        "ORDER BY id DESC LIMIT 1", (task, agent)).fetchone()


def main(argv: list) -> int:
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    cmd = argv[0]

    if cmd == "init-schema":
        conn_for(argv[1]).close()

    elif cmd == "journal-task":
        # journal-task <db> <agent> <task_id> <status> [reason] [ts]
        db, agent, task, status = argv[1], argv[2], argv[3], argv[4]
        reason = argv[5] if len(argv) > 5 else ""
        ts = int(argv[6]) if len(argv) > 6 else int(time.time())
        conn = conn_for(db)
        conn.execute(
            "INSERT INTO task_rewards (task_id, handle, status, reason, ts) VALUES (?,?,?,?,?)",
            (task, agent, status, reason, ts))
        conn.commit()
        conn.close()

    elif cmd == "journal-introspect":
        # journal-introspect <db> <agent> <task_id> <title> <category> <verification>
        db, agent, task = argv[1], argv[2], argv[3]
        title, category, verification = argv[4], argv[5], argv[6]
        conn = conn_for(db)
        row = latest_row(conn, task, agent)
        if row is None:
            conn.execute(
                "INSERT INTO task_rewards (task_id, handle, status, task_title, category, verification, ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (task, agent, "introspected", title, category, verification, int(time.time())))
        else:
            conn.execute(
                "UPDATE task_rewards SET task_title=?, category=?, verification=? "
                "WHERE id=?", (title, category, verification, row[0]))
        conn.commit()
        conn.close()

    elif cmd == "journal-proof":
        # journal-proof <db> <agent> <task_id> <deliverable_path> <proof_type> <proof_hash> <signature> <signer_addr>
        db, agent, task = argv[1], argv[2], argv[3]
        dpath, ptype, phash, sig, signer = argv[4], argv[5], argv[6], argv[7], argv[8]
        conn = conn_for(db)
        row = latest_row(conn, task, agent)
        if row is None:
            conn.execute(
                "INSERT INTO task_rewards (task_id, handle, status, deliverable_path, proof_type, "
                "proof_hash, signature, signer_addr, ts) VALUES (?,?,?,?,?,?,?,?,?)",
                (task, agent, "proof", dpath, ptype, phash, sig, signer, int(time.time())))
        else:
            conn.execute(
                "UPDATE task_rewards SET deliverable_path=?, proof_type=?, proof_hash=?, "
                "signature=?, signer_addr=?, status='proof' WHERE id=?",
                (dpath, ptype, phash, sig, signer, row[0]))
        conn.commit()
        conn.close()

    elif cmd == "introspect-task-file":
        # introspect-task-file <db> <agent> <task_json_file>
        # Reads a saved `pivx-agent-kit task get` JSON and journals its
        # title/category/verification onto the latest row for that task.
        db, agent, task_file = argv[1], argv[2], argv[3]
        with open(task_file, "r", encoding="utf-8") as fh:
            task = json.load(fh)
        task_id = str(task.get("id") or task.get("task_id") or "")
        title = str(task.get("title") or "")[:300]
        category = str(task.get("category") or "")
        verification = str(task.get("verification") or "")[:500]
        conn = conn_for(db)
        row = latest_row(conn, task_id, agent)
        if row is None:
            conn.execute(
                "INSERT INTO task_rewards (task_id, handle, status, task_title, category, verification, ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (task_id, agent, "introspected", title, category, verification, int(time.time())))
        else:
            conn.execute(
                "UPDATE task_rewards SET task_title=?, category=?, verification=? "
                "WHERE id=?", (title, category, verification, row[0]))
        conn.commit()
        conn.close()

    elif cmd == "journal-reward-txid":
        # journal-reward-txid <db> <agent> <task_id> <txid>
        db, agent, task, txid = argv[1], argv[2], argv[3], argv[4]
        conn = conn_for(db)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO task_rewards (task_id, handle, status, reason, ts) "
            "VALUES (?, ?, 'paid-txid', ?, ?)",
            (task, agent, txid, int(time.time())))
        conn.commit()
        conn.close()
        print("ok")

    elif cmd == "inflight":
        # inflight <db> <agent> — latest rows per task whose status is still open
        db, agent = argv[1], argv[2]
        conn = conn_for(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT task_id, status, reason FROM task_rewards t "
            "WHERE handle = ? AND status IN ('signed-up','proof','submitted','approved') "
            "AND id = (SELECT MAX(id) FROM task_rewards u "
            "          WHERE u.task_id = t.task_id AND u.handle = t.handle)",
            (agent,)).fetchall()
        print(json.dumps([dict(r) for r in rows]))
        conn.close()

    elif cmd == "latest":
        # latest <db> <agent> <task_id>  → JSON of the latest row (or null)
        db, agent, task = argv[1], argv[2], argv[3]
        conn = conn_for(db)
        row = latest_row(conn, task, agent)
        cols = [d[1] for d in conn.execute("PRAGMA table_info(task_rewards)")]
        conn.close()
        if row is None:
            print("null")
        else:
            print(json.dumps(dict(zip(cols, row))))

    elif cmd == "count-signed-up":
        # count-signed-up <db> <agent>
        db, agent = argv[1], argv[2]
        conn = conn_for(db)
        row = conn.execute(
            "SELECT COUNT(*) FROM task_rewards WHERE handle=? AND status IN "
            "('signed-up','submitted','approved','paid','disputed')",
            (agent,)).fetchone()
        conn.close()
        print(row[0] or 0)

    elif cmd == "journal-spend":
        # journal-spend <db> <agent> <ts> <amount_sat> <outcome>
        db, agent, ts, sat = argv[1], argv[2], int(argv[3]), int(argv[4])
        outcome = argv[5]
        conn = conn_for(db)
        conn.execute(
            "INSERT INTO spend_events (agent, ts, direction, amount_sat, allowed, reason)"
            " VALUES (?,?,?,?,?,?)",
            (agent, ts, "out", sat, 0 if outcome != "allowed" else 1, outcome))
        conn.commit()
        conn.close()

    elif cmd == "spent-today":
        # spent-today <db> <now>
        db, now = argv[1], int(argv[2])
        conn = conn_for(db)
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_sat),0) FROM spend_events "
                "WHERE direction='out' AND allowed=1 AND ts >= ?",
                (now - 86400,)).fetchone()
            print(row[0] or 0)
        except sqlite3.Error:
            print(0)
        conn.close()

    else:
        sys.stderr.write(f"ledger.py: unknown subcommand '{cmd}'\n")
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
