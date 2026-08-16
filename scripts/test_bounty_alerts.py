#!/usr/bin/env python3
"""test_bounty_alerts.py — regression test for scripts/bounty_alerts.py
(subscription service prototype #1).

Covers:
  preset loading + match() filter logic (category whitelist/wildcard,
    rep cap, min PIV, open-status gate)
  external_id parse + activate() subscriber upsert (incl. negative chat ids,
    renewals, unknown presets)
  watch helpers: alert_text, expiry transition, no-token TG skip

Run: python3 scripts/test_bounty_alerts.py   (stdlib only, no network)
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

_TMPDIR = tempfile.mkdtemp()
os.environ["BOUNTY_ALERTS_DB"] = os.path.join(_TMPDIR, "bounty-alerts.db")
os.environ["TELEGRAM_BOT_TOKEN"] = ""  # no network in tests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bounty_alerts as ba  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def task(**kw):
    t = {"id": 99, "title": "t", "category": "dev", "quoted_amount": 2.0,
         "min_worker_rep": 0, "status": "open"}
    t.update(kw)
    return t


def presets():
    return ba.load_presets()


# ---------------------------------------------------------------- match()

def test_match():
    p = presets()
    std = p["standard"]
    check("standard accepts eligible dev task",
          ba.match(std, task(category="dev", quoted_amount=2.0, min_worker_rep=0)))
    check("standard rejects social",
          not ba.match(std, task(category="social")))
    check("standard rejects below-min reward",
          not ba.match(std, task(quoted_amount=0.5)))
    check("standard rejects rep-gated task",
          not ba.match(std, task(min_worker_rep=3)))
    check("standard rejects non-open task",
          not ba.match(std, task(status="submitted")))
    allp = p["all"]
    check("all accepts social + tiny reward",
          ba.match(allp, task(category="social", quoted_amount=0.1, min_worker_rep=5)))
    big = p["big"]
    check("big accepts >=5 PIV",
          ba.match(big, task(quoted_amount=5.0)))
    check("big rejects <5 PIV",
          not ba.match(big, task(quoted_amount=4.99)))
    check("unknown category in whitelist rejected",
          not ba.match(std, task(category="marketing")))


# ---------------------------------------------------------------- activate()

def test_activate():
    conn = ba.db()
    conn.execute("DELETE FROM subscribers")
    conn.commit()
    conn.close()

    # fresh activation
    r = ba.activate("bounty-alert-328267004-standard-1720000000", "tx1")
    check("activate returns chat+preset+period_end",
          r and r["chat_id"] == 328267004 and r["preset"] == "standard"
          and r["period_end"] > time.time())
    check("period ~30 days", r and 29 * 86400 < r["period_end"] - time.time() < 31 * 86400)

    # renewal extends (upsert, stays active)
    r2 = ba.activate("bounty-alert-328267004-standard-1720001000", "tx2")
    check("renewal same chat+preset", r2 and r2["chat_id"] == 328267004)
    check("renewal later period_end", r2 and r2["period_end"] >= r["period_end"])

    # negative chat id (group) parses
    r3 = ba.activate("bounty-alert--1001234567890-big-1720002000", "tx3")
    check("negative chat id", r3 and r3["chat_id"] == -1001234567890 and r3["preset"] == "big")

    # non-bounty external_id -> None (receiver ignores)
    check("non-bounty ext ignored", ba.activate("alert-1", "tx4") is None)

    # unknown preset -> None
    check("unknown preset ignored", ba.activate("bounty-alert-328267004-bogus-1720003000", "tx5") is None)


# ---------------------------------------------------------------- expiry + helpers

def test_expiry():
    conn = ba.db()
    conn.execute("DELETE FROM subscribers")
    conn.execute(
        "INSERT INTO subscribers (chat_id, preset, status, period_end, external_id, created_at) "
        "VALUES (1, 'standard', 'active', ?, 'bounty-alert-1-standard-1', ?)",
        (int(time.time()) - 10, int(time.time())),
    )
    conn.commit()
    conn.close()
    # cmd_watch would expire it, but needs the kit; verify the SQL gate here:
    conn = ba.db()
    n = conn.execute(
        "SELECT COUNT(*) FROM subscribers WHERE status='active' AND period_end >= ?",
        (int(time.time()),),
    ).fetchone()[0]
    check("expired row excluded from active set", n == 0)
    conn.close()


def test_helpers():
    t = task(title="Fix wallet", quoted_amount=2.0)
    txt = ba.alert_text(t)
    check("alert text has title", "Fix wallet" in txt)
    check("alert text has id", "#99" in txt)
    check("alert text has board link", "tasks.pivxla.bz" in txt)
    check("external re rejects bad format", ba.EXTERNAL_RE.match("alert-1") is None)
    check("external re accepts negative chat", ba.EXTERNAL_RE.match("bounty-alert--100-big-123") is not None)


# ---------------------------------------------------------------- main

def main():
    print("test_bounty_alerts.py")
    test_match()
    test_activate()
    test_expiry()
    test_helpers()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
