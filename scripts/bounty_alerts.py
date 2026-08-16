#!/usr/bin/env python3
"""Bounty-alert subscription service (prototype #1).

Sell: Telegram alerts when new eligible tasks appear on the PIVX Tasks board,
paid for in PIV through the merchant kit (1 PIV / 30 days by default).

Flow:
  seller runs:  bounty_alerts.py subscribe --chat <id> --preset <name>
                -> creates a merchant invoice, prints the payment address
  buyer pays    the invoice address (any PIV wallet)
  receiver      (merchant-webhook-receiver.py) calls activate() on
                invoice.confirmed -> subscriber row goes active
  cron runs:    bounty_alerts.py watch
                -> polls the board, TG-alerts each active subscriber once per
                   new task matching their preset, expires past-due subs

Subcommands: subscribe | activate | watch | list
Env: TELEGRAM_BOT_TOKEN (alerts), PIVX_AGENT (unused here; kit defaults).
Stdlib only. The merchant auth token is read from the live config at runtime
and never printed.
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
PRESETS = os.path.join(REPO_ROOT, "config", "bounty-alert-presets.json")
DB_PATH = os.environ.get(
    "BOUNTY_ALERTS_DB", os.path.expanduser("~/.local/share/pivx-agent-kit/bounty-alerts.db")
)
MERCHANT_API = os.environ.get("MERCHANT_API", "http://127.0.0.1:7474")
MERCHANT_CONFIG = os.path.expanduser("~/.config/pivx-merchant/merchant-config.toml")
KIT = os.path.expanduser("~/.local/bin/pivx-agent-kit")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DEFAULT_PIV = 1.0
DEFAULT_DAYS = 30

EXTERNAL_RE = re.compile(r"^bounty-alert-(-?\d+)-([a-z0-9_]+)-\d+$")


# ---------------------------------------------------------------- db

def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subscribers (
            chat_id     INTEGER NOT NULL,
            preset      TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'active',
            period_end  INTEGER NOT NULL,
            external_id TEXT UNIQUE,
            txid        TEXT,
            created_at  INTEGER NOT NULL,
            PRIMARY KEY (chat_id, preset)
        );
        CREATE TABLE IF NOT EXISTS alerted (
            chat_id     INTEGER NOT NULL,
            task_id     INTEGER NOT NULL,
            alerted_at  INTEGER NOT NULL,
            PRIMARY KEY (chat_id, task_id)
        );
        """
    )
    return conn


# ---------------------------------------------------------------- presets

def load_presets():
    with open(PRESETS) as f:
        return json.load(f)


def match(preset, task):
    """True if the open task passes the preset filter."""
    if task.get("status") != "open":
        return False
    cats = preset.get("categories", ["*"])
    if "*" not in cats and task.get("category") not in cats:
        return False
    try:
        if int(task.get("min_worker_rep") or 0) > int(preset.get("rep_cap", 0)):
            return False
    except (TypeError, ValueError):
        pass
    try:
        piv = float(task.get("quoted_amount") or 0)
    except (TypeError, ValueError):
        piv = 0.0
    if piv < float(preset.get("min_piv", 0)):
        return False
    return True


# ---------------------------------------------------------------- tg

def tg(chat_id, text):
    if not TG_TOKEN:
        print(f"[tg] no TELEGRAM_BOT_TOKEN, skipping alert to {chat_id}")
        return False
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception as e:
        print(f"[tg] failed: {e}")
        return False


def alert_text(t):
    return (
        f"🆕 PIVX bounty #{t.get('id')}\n"
        f"{t.get('title', '?')}\n"
        f"💰 {t.get('quoted_amount')} PIV · {t.get('category')} · rep {t.get('min_worker_rep')}\n"
        f"https://tasks.pivxla.bz (search #{t.get('id')})"
    )


# ---------------------------------------------------------------- merchant api

def merchant_auth():
    """Read the auth token from the live daemon config (never echoed)."""
    try:
        with open(MERCHANT_CONFIG) as f:
            m = re.search(r'^\s*auth_token\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def create_invoice(external_id, amount_piv, expires_in_secs=3600):
    auth = merchant_auth()
    if not auth:
        raise RuntimeError(f"no auth_token found in {MERCHANT_CONFIG}")
    body = json.dumps({
        "external_id": external_id,
        "channel": "transparent",
        "amount_due_sat": int(round(amount_piv * 1e8)),
        "expires_in_secs": expires_in_secs,
        "metadata": {"service": "bounty-alerts", "external_id": external_id},
    }).encode()
    req = urllib.request.Request(
        f"{MERCHANT_API}/v1/invoices",
        data=body,
        headers={"Authorization": f"Bearer {auth}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"merchant API {e.code}: {e.read()[:300]}")


# ---------------------------------------------------------------- commands

def cmd_subscribe(args):
    presets = load_presets()
    if args.preset not in presets:
        print(f"unknown preset '{args.preset}' — choose: {', '.join(presets)}")
        return 2
    ext = f"bounty-alert-{args.chat}-{args.preset}-{int(time.time())}"
    inv = create_invoice(ext, args.amount_piv)
    addr = inv.get("address", "?")
    print(f"invoice {inv.get('id', '?')} · {inv.get('status')}")
    print(f"external_id {ext}")
    print(f"amount {inv.get('amount_due_sat', 0) / 1e8} PIV")
    print(f"pay to {addr}")
    print(f"expires {time.strftime('%Y-%m-%d %H:%M', time.localtime(inv.get('expires_at', 0)))}")
    print(f"send: pivx-agent-kit send {addr} {args.amount_piv} --from public")
    return 0


def activate(external_id, txid=None):
    """Receiver hook: activate a subscriber from a confirmed invoice.

    Returns dict(chat_id, preset, period_end) or None if not a bounty-alert
    external_id / already active.
    """
    m = EXTERNAL_RE.match(external_id or "")
    if not m:
        return None
    chat_id, preset = int(m.group(1)), m.group(2)
    presets = load_presets()
    if preset not in presets:
        print(f"[bounty-alerts] unknown preset '{preset}' in {external_id}")
        return None
    now = int(time.time())
    period_end = now + int(DEFAULT_DAYS * 86400)
    conn = db()
    conn.execute(
        """INSERT INTO subscribers (chat_id, preset, status, period_end, external_id, txid, created_at)
           VALUES (?, ?, 'active', ?, ?, ?, ?)
           ON CONFLICT(chat_id, preset) DO UPDATE SET
             status='active', period_end=?, txid=COALESCE(excluded.txid, subscribers.txid)""",
        (chat_id, preset, period_end, external_id, txid, now, period_end),
    )
    conn.commit()
    conn.close()
    print(f"[bounty-alerts] activated chat {chat_id} preset '{preset}' until {period_end}")
    return {"chat_id": chat_id, "preset": preset, "period_end": period_end}


def cmd_watch(args):
    conn = db()
    now = int(time.time())

    # expire past-due subscriptions
    for chat_id, preset in conn.execute(
        "SELECT chat_id, preset FROM subscribers WHERE status='active' AND period_end < ?", (now,)
    ).fetchall():
        conn.execute("UPDATE subscribers SET status='expired' WHERE chat_id=? AND preset=?", (chat_id, preset))
        tg(chat_id, "⏰ Bounty alert subscription expired — renew with a new payment to keep alerts flowing.")
    conn.commit()

    active = conn.execute(
        "SELECT chat_id, preset FROM subscribers WHERE status='active' AND period_end >= ?", (now,)
    ).fetchall()
    if not active:
        conn.close()
        print("0 alerts (no active subscribers)")
        return 0

    try:
        proc = subprocess.run([KIT, "task", "list"], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        conn.close()
        print(f"0 alerts (task list failed: {e})")
        return 0
    if proc.returncode != 0:
        conn.close()
        print(f"0 alerts (task list rc={proc.returncode})")
        return 0
    data = json.loads(proc.stdout, strict=False)
    tasks = data.get("items", data) if isinstance(data, dict) else data
    presets = load_presets()

    sent = 0
    for chat_id, preset_name in active:
        preset = presets.get(preset_name, presets["standard"])
        for t in tasks:
            if not match(preset, t):
                continue
            seen = conn.execute(
                "SELECT 1 FROM alerted WHERE chat_id=? AND task_id=?", (chat_id, t.get("id"))
            ).fetchone()
            if seen:
                continue
            tg(chat_id, alert_text(t))
            conn.execute(
                "INSERT OR IGNORE INTO alerted (chat_id, task_id, alerted_at) VALUES (?,?,?)",
                (chat_id, t.get("id"), now),
            )
            sent += 1
    conn.commit()
    conn.close()
    print(f"{sent} alerts sent")
    return 0


def cmd_list(args):
    conn = db()
    for r in conn.execute(
        "SELECT chat_id, preset, status, period_end, external_id FROM subscribers ORDER BY created_at DESC"
    ):
        print(f"{r[0]} {r[1]} {r[2]} until {time.strftime('%Y-%m-%d', time.localtime(r[3]))} ({r[4]})")
    conn.close()
    return 0


# ---------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("subscribe", help="create a subscription invoice")
    s.add_argument("--chat", type=int, required=True, help="buyer Telegram chat_id")
    s.add_argument("--preset", required=True, help="filter preset (standard/all/big)")
    s.add_argument("--amount-piv", type=float, default=DEFAULT_PIV)
    s.add_argument("--days", type=int, default=DEFAULT_DAYS, help="subscription length (reserved)")

    a = sub.add_parser("activate", help="receiver hook: activate from confirmed invoice")
    a.add_argument("external_id")
    a.add_argument("--txid", default="")

    sub.add_parser("watch", help="cron: poll board, alert subscribers, expire past-due")
    sub.add_parser("list", help="show subscribers")

    args = p.parse_args()
    if args.cmd == "subscribe":
        return cmd_subscribe(args)
    if args.cmd == "activate":
        return 0 if activate(args.external_id, args.txid) else 1
    if args.cmd == "watch":
        return cmd_watch(args)
    if args.cmd == "list":
        return cmd_list(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
