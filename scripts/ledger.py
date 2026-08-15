#!/usr/bin/env python3
"""ledger.py — shared SQLite ledger access for the PIVX agent economy scripts.

Replaces the inline `python3 - <<'PYEOF'` heredocs that used to live in
task-runner.sh and enforce-limits.sh (repo rule: no heredocs, file-based
scripting only).

Subcommands:
  init-schema <db>                       create task_rewards + spend_events if missing
  journal-task <db> <agent> <task_id> <status> [reason] [ts]
  count-signed-up <db> <agent>           gate metric: rows with REAL signup progress
  journal-spend <db> <agent> <ts> <amount_sat> <outcome>
  spent-today <db> <now>                 sum of allowed out-spend in last 24 h

Stdlib only.
"""
import sqlite3
import sys
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_rewards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    handle      TEXT NOT NULL,
    bounty_sat  INTEGER,
    status      TEXT NOT NULL DEFAULT 'applied',
    txid        TEXT,
    reason      TEXT,
    ts          INTEGER NOT NULL
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

# Statuses that mean the agent actually progressed past the gate. 'applied'
# and 'pending-approval' rows are pre-inserted before anything real happens
# and MUST NOT open the gate (bug list #6).
REAL_SIGNUP_STATUSES = ("signed-up", "submitted", "approved", "paid", "disputed")


def conn_for(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    return conn


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
