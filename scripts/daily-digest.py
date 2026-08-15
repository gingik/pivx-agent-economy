#!/usr/bin/env python3
"""daily-digest.py — SQLite ledger → Telegram summary (M3).

Sends a daily summary of wallet balances, task rewards, and merchant orders.
Cron: 0 7 * * *  (or via Hermes cron / n8n Schedule)

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (required), LEDGER_DB (default below).
Usage: python3 daily-digest.py [agent]
"""
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request

AGENT = sys.argv[1] if len(sys.argv) > 1 else "hermes-main"
LEDGER_DB = os.environ.get("LEDGER_DB", os.path.expanduser("~/.local/share/pivx-agent-kit/ledger.db"))
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

def balance():
    out = subprocess.run(
        ["pivx-agent-kit", "balance"], capture_output=True, text=True,
        env={**os.environ, "PIVX_AGENT": AGENT},
    ).stdout
    try:
        b = json.loads(out)
        return b.get("public_balance", 0), b.get("private_balance", 0)
    except Exception:
        return None, None

def ledger_summary():
    conn = sqlite3.connect(LEDGER_DB)
    rows = {}
    try:
        rows["rewards_today"] = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bounty_sat),0) FROM task_rewards WHERE ts >= strftime('%s','now','-1 day')"
        ).fetchone()
        rows["orders_today"] = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount_sat),0) FROM orders WHERE created_at >= strftime('%s','now','-1 day')"
        ).fetchone()
        rows["open_orders"] = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status='pending'"
        ).fetchone()
    finally:
        conn.close()
    return rows

def tg(text: str):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TG_CHAT, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

if __name__ == "__main__":
    pub, priv = balance()
    l = ledger_summary()
    lines = [
        f"📊 PIVX daily digest — {AGENT}",
        f"Transparent: {pub} PIV | Shield: {priv} PIV",
        f"Task rewards today: {l['rewards_today'][0]} ({l['rewards_today'][1] / 1e8} PIV)",
        f"Orders today: {l['orders_today'][0]} ({l['orders_today'][1] / 1e8} PIV)",
        f"Open orders: {l['open_orders'][0]}",
    ]
    tg("\n".join(lines))
    print("\n".join(lines))
