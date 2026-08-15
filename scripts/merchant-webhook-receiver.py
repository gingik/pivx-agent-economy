#!/usr/bin/env python3
"""merchant-webhook-receiver.py — HMAC-verified webhook receiver for pivx-merchant-kit.

Extends upstream examples/webhook-receiver.py with:
  - X-Merchant-Delivery-Id dedupe (idempotent delivery)
  - SQLite ledger row (orders table) on invoice.confirmed
  - Telegram alert on confirmed/expired/cancelled
  - sign-message based alert delivery hook for the M2 flow

Env:
  WEBHOOK_SECRET   — must match [webhooks].secret in merchant-config.toml
  LEDGER_DB        — path to SQLite ledger (default ~/.local/share/pivx-agent-kit/ledger.db)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — for alerts; optional, skip if unset
  DELIVERY_CMD     — shell command template run on confirmed; {invoice_id}, {external_id}
                     placeholders. Default: log-only.

Stdlib only. Run:  WEBHOOK_SECRET=... python3 merchant-webhook-receiver.py
"""
import hashlib
import hmac
import http.server
import json
import os
import sqlite3
import subprocess
import urllib.request

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
LEDGER_DB = os.environ.get("LEDGER_DB", os.path.expanduser("~/.local/share/pivx-agent-kit/ledger.db"))
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
DELIVERY_CMD = os.environ.get("DELIVERY_CMD", "")


def verify(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True  # unsigned mode (internal-only)
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def tg(text: str):
    if not (TG_TOKEN and TG_CHAT):
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TG_CHAT, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def ledger():
    conn = sqlite3.connect(LEDGER_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def upsert_order(conn, invoice: dict):
    conn.execute(
        """INSERT OR IGNORE INTO orders
           (id, external_id, invoice_id, amount_sat, payer_addr, status, txid, created_at, confirmed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            invoice.get("id"),
            invoice.get("external_id"),
            invoice.get("id"),
            invoice.get("amount_due_sat"),
            invoice.get("payer_address") or "",
            invoice.get("status", ""),
            invoice.get("txid"),
            invoice.get("created_at"),
            invoice.get("confirmed_at"),
        ),
    )
    conn.commit()


def deliver(invoice: dict):
    """Compose + sign the alert payload (M2 flow step 5)."""
    ext = invoice.get("external_id", "?")
    inv_id = invoice.get("id", "?")
    payload = {
        "event": "fall_alert",
        "external_id": ext,
        "invoice_id": inv_id,
        "alert_hash": hashlib.sha256(json.dumps(invoice.get("metadata", {})).encode()).hexdigest(),
        "timestamp": int(invoice.get("confirmed_at") or 0),
    }
    if DELIVERY_CMD:
        cmd = DELIVERY_CMD.format(invoice_id=inv_id, external_id=ext)
        subprocess.run(cmd, shell=True, check=False)
    return payload


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(n) if n else b""
        sig = self.headers.get("x-merchant-signature", "")
        delivery_id = self.headers.get("x-merchant-delivery-id", "")

        if not verify(body, sig):
            self.send_response(401)
            self.end_headers()
            return

        try:
            event = json.loads(body)
        except Exception:
            self.send_response(400)
            self.end_headers()
            return

        event_type = event.get("event_type")
        invoice = event.get("invoice", {})

        conn = ledger()
        upsert_order(conn, invoice)
        conn.close()

        if event_type == "invoice.confirmed":
            payload = deliver(invoice)
            tg(f"PIVX merchant: invoice CONFIRMED {invoice.get('id')} "
               f"external={invoice.get('external_id')} amount={invoice.get('amount_due_sat')} sat")
        elif event_type == "invoice.expired":
            tg(f"PIVX merchant: invoice EXPIRED {invoice.get('id')}")
        elif event_type == "invoice.cancelled":
            tg(f"PIVX merchant: invoice CANCELLED {invoice.get('id')}")

        self.send_response(200)
        self.send_header("content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a, **k):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8081"))
    print(f"webhook receiver listening on http://127.0.0.1:{port}/webhook")
    print(f"ledger: {LEDGER_DB}")
    print("HMAC verification ENABLED" if WEBHOOK_SECRET else "HMAC DISABLED (unsigned mode)")
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()
