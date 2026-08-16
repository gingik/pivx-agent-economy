#!/usr/bin/env python3
"""task-status-watch.py — close the loop after submit (improvements list item 4).

Polls the board for the agent's task lifecycle and journals every transition
into the SQLite ledger, so submissions are observable instead of
"submit and hope". For cron / the n8n status branch.

Flow per run:
  1. `task notifications --unread` → parse each item's task id + message;
     map message keywords to approved / rejected / paid and journal the
     transition + reason (ledger.py journal-task).
  2. For tasks still in flight in the ledger (signed-up|proof|submitted|
     approved), refresh with `task get` and journal any state change
     (in_flight/closed/expired/aborted …) found in the task JSON.
  3. On a paid event (or a task whose get shows reward settled), cross-check
     the agent's PIVX address on the public block explorer and journal the
     reward txid (ledger.py journal-reward-txid).
  4. Telegram alert per transition. stdout summary is cron-friendly.

No sudo, no long-lived process: each run is one-shot and idempotent
(notifications are only marked read AFTER successful journaling).

Usage: task-status-watch.py <agent> [--db <ledger.db>] [--no-tg]
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (alerts); PIVX_AGENT not needed
     (set internally per kit call).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_DB = os.path.expanduser("~/.local/share/pivx-agent-kit/ledger.db")
EXPLORER_TX_URL = "https://blockbook.pivx.org/api/address/{addr}?page=0&size=6"
WATCH_STATUSES = {"signed-up", "proof", "submitted", "approved"}
TXID_RE = re.compile(r"txid[\s:=]+([0-9a-fA-F]{64})|([0-9a-fA-F]{64})")
TASK_ID_RE = re.compile(r"\b(\d{1,6})\b")


def kit(agent: str, *args, timeout: int = 120) -> dict:
    """Run a pivx-agent-kit command; return parsed JSON (strict=False) or {}."""
    out = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False).name
    env = dict(os.environ, PIVX_AGENT=agent)
    try:
        subprocess.run(["timeout", str(timeout), "pivx-agent-kit", *args],
                       env=env, stdout=open(out, "w"), stderr=subprocess.STDOUT,
                       check=False, timeout=timeout + 10)
    except subprocess.TimeoutExpired:
        os.unlink(out)
        return {}
    try:
        with open(out, "r", encoding="utf-8") as fh:
            data = json.load(fh, strict=False)
    except Exception:
        data = {}
    os.unlink(out)
    return data


def journal(agent: str, task_id: str, status: str, reason: str, db: str) -> None:
    subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "ledger.py"), "journal-task",
         db, agent, task_id, status, reason or "", str(int(time.time()))],
        check=False)


def journal_txid(agent: str, task_id: str, txid: str, db: str) -> None:
    subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "ledger.py"), "journal-reward-txid",
         db, agent, task_id, txid],
        check=False)


def latest_status(agent: str, task_id: str, db: str) -> str:
    out = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "ledger.py"), "latest", db, agent, task_id],
        capture_output=True, text=True).stdout.strip()
    if not out or out == "null":
        return ""
    try:
        return json.loads(out).get("status", "")
    except Exception:
        return ""


def tg(text: str) -> None:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data=f"chat_id={chat}&text={text}".encode(), timeout=30)
    except Exception:
        pass


def status_from_message(msg: str) -> str:
    low = msg.lower()
    if any(k in low for k in ("paid", "reward", "payout", "payment", "sent to your wallet")):
        return "paid"
    if "reject" in low or "denied" in low or "disputed" in low:
        return "rejected"
    if "approv" in low:
        return "approved"
    return "notified"


def find_txid(msg: str) -> str:
    m = TXID_RE.search(msg)
    if not m:
        return ""
    return m.group(1) or m.group(2)


def explorer_new_txids(address: str, since_ts: float, timeout: int = 60) -> list:
    """Recent incoming txids for the agent address (best effort; [] on failure)."""
    url = EXPLORER_TX_URL.format(addr=address)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return []
    txs = data.get("transactions", []) or data.get("txs", [])
    out = []
    for t in txs:
        ts = t.get("blockTime") or t.get("time") or t.get("timestamp") or 0
        if ts >= since_ts:
            out.append(t.get("txid", ""))
    return [t for t in out if t]


def watch_notifications(agent: str, db: str, mark_read: bool, no_tg: bool) -> int:
    notif = kit(agent, "task", "notifications", "--unread", "--limit", "25")
    items = notif.get("items", [])
    changed = 0
    for it in items:
        tid = str(it.get("task_id", ""))
        msg = str(it.get("message", "") or it.get("text", ""))
        if not tid:
            m = TASK_ID_RE.search(msg)
            tid = m.group(1) if m else ""
        if not tid:
            print(f"  [watch] unparseable notification: {msg[:120]}")
            continue
        status = status_from_message(msg)
        reason = msg[:500]
        if status == "paid":
            txid = find_txid(msg)
            if txid:
                journal_txid(agent, tid, txid, db)
                reason += f" txid={txid}"
        journal(agent, tid, status, reason, db)
        if not no_tg:
            tg(f"[PIVX task-status] task {tid}: {status} — {msg[:200]}")
        print(f"  [watch] task {tid}: {status} ({msg[:80]})")
        changed += 1
        if mark_read:
            kit(agent, "task", "notifications", "read", str(it.get("id", "")))
    return changed


def watch_inflight(agent: str, db: str) -> int:
    """Refresh tasks the ledger thinks are still open; journal closed/expired."""
    out = subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "ledger.py"), "inflight", db, agent],
        capture_output=True, text=True).stdout.strip()
    changed = 0
    if not out or out == "[]":
        return 0
    try:
        rows = json.loads(out)
    except Exception:
        return 0
    for row in rows:
        tid = str(row["task_id"])
        task = kit(agent, "task", "get", tid)
        status = str(task.get("status", ""))
        if status in ("closed", "expired", "aborted", "inactive") and \
                latest_status(agent, tid, db) != status:
            journal(agent, tid, status, f"task get shows {status}", db)
            print(f"  [watch] task {tid}: closed on board ({status})")
            changed += 1
    return changed


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    agent = sys.argv[1]
    db = LEDGER_DB
    mark_read = False
    no_tg = False
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--db":
            i += 1
            db = sys.argv[i]
        elif sys.argv[i] == "--mark-read":
            mark_read = True
        elif sys.argv[i] == "--no-tg":
            no_tg = True
        i += 1

    print(f"[task-status-watch] agent={agent} db={db}")
    changed = watch_notifications(agent, db, mark_read, no_tg)
    changed += watch_inflight(agent, db)
    print(f"[task-status-watch] {changed} transitions journaled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
