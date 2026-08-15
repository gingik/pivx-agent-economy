#!/usr/bin/env python3
"""merchant-webhook-receiver.py — HMAC-verified, idempotent webhook receiver.

Extends upstream examples/webhook-receiver.py with the M2 agent-economy flow.
Fixes from the bug list (2026-08-15):

  #1  txid: merchant-kit nests payment data at invoice["payments"][N]["txid"]
      (NOT invoice["txid"] — that key does not exist). Ledger rows now store
      the real txid, which test T3 needs to resolve on the explorer. Payer
      address comes from invoice["address"] (the funded invoice address);
      there is no "payer_address" key in the payload.
  #2  Idempotency: the dedupe contract is X-Merchant-Delivery-Id — a NEW UUID
      per delivery attempt of the SAME event (retry-safe), not the invoice id.
      Every delivery id is recorded in webhook_deliveries; repeats are skipped.
      Status transitions (pending -> confirmed/expired/cancelled) UPDATE the
      existing orders row instead of being swallowed by INSERT OR IGNORE.
  #3  M2 signature flow: on confirmed, alert_hash is computed over the ALERT
      CONTENT (the merchant's metadata payload), then
        pivx-agent-kit sign-message "<alert_hash>:<invoice_id>:<confirmed_at>"
      produces a buyer-verifiable signature. address + signature are stored on
      the row (signer_addr, signature) and passed to the delivery hook.
  #4  Delivery hook: DELIVERY_CMD is shlex-split into an argv list and exec'd
      with NO shell — external_id comes from the invoice creator (untrusted
      buyer); shell interpolation would be command injection.

Wire format (verified against upstream src/webhooks/):
  Headers: x-merchant-event-type, x-merchant-delivery-id, x-merchant-signature
  Body:    {"event_id", "event_type", "created_at", "invoice": InvoiceResponse}

Env:
  WEBHOOK_SECRET   — must match [webhooks].secret in merchant-config.toml
  LEDGER_DB        — SQLite ledger path
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — optional alerts
  PIVX_AGENT       — agent whose key signs deliveries (default hermes-main)
  DELIVERY_CMD     — template with {invoice_id} {external_id} {txid}
                     {alert_hash} {signature} {signer_address} {timestamp}
                     placeholders; argv-split, NO shell. Default: log-only.

Stdlib only. Run:  WEBHOOK_SECRET=... python3 merchant-webhook-receiver.py
"""
import hashlib
import hmac
import http.server
import json
import os
import shlex
import sqlite3
import subprocess
import time
import urllib.request

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
LEDGER_DB = os.environ.get(
    "LEDGER_DB", os.path.expanduser("~/.local/share/pivx-agent-kit/ledger.db")
)
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
DELIVERY_CMD = os.environ.get("DELIVERY_CMD", "")
KIT_AGENT = os.environ.get("PIVX_AGENT", "hermes-main")
KIT = os.path.expanduser("~/.local/bin/pivx-agent-kit")

PLACEHOLDERS = ("invoice_id", "external_id", "txid", "alert_hash",
                "signature", "signer_address", "timestamp")


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
    req = urllib.request.Request(
        url, data=data, headers={"content-type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # alerts must never crash the webhook
        print(f"[tg] failed: {e}")


def ledger():
    conn = sqlite3.connect(LEDGER_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        -- orders (mirrors config/ledger-schema.sql; receiver is self-sufficient
        -- on a fresh DB, CREATE IF NOT EXISTS is a no-op on an existing one)
        CREATE TABLE IF NOT EXISTS orders (
            id           TEXT PRIMARY KEY,
            external_id  TEXT UNIQUE,
            invoice_id   TEXT,
            amount_sat   INTEGER NOT NULL,
            payer_addr   TEXT,
            status       TEXT NOT NULL DEFAULT 'pending',
            txid         TEXT,
            alert_hash   TEXT,
            signature    TEXT,
            signer_addr  TEXT,
            created_at   INTEGER NOT NULL,
            confirmed_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_external ON orders(external_id);
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            delivery_id TEXT PRIMARY KEY,   -- X-Merchant-Delivery-Id (per-attempt UUID)
            invoice_id  TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            received_at INTEGER NOT NULL
        );
        """
    )
    # legacy DBs created before signer_addr existed
    cols = [r[1] for r in conn.execute("PRAGMA table_info(orders)")]
    if "signer_addr" not in cols:
        conn.execute("ALTER TABLE orders ADD COLUMN signer_addr TEXT")
    conn.commit()
    return conn


def payments_txid(invoice: dict) -> str:
    """#1: txids live under payments[], never at the top level."""
    return ",".join(
        p.get("txid") for p in (invoice.get("payments") or []) if p.get("txid")
    )


def payment_confirmed_at(invoice: dict):
    for p in invoice.get("payments") or []:
        if p.get("confirmed_at"):
            return p["confirmed_at"]
    return None


def upsert_order(conn, invoice: dict):
    """#2: INSERT new invoice, then UPDATE on every delivery (status transitions)."""
    inv_id = invoice.get("id")
    if not inv_id:
        return
    status = invoice.get("status") or "pending"
    txid = payments_txid(invoice)
    confirmed_at = payment_confirmed_at(invoice)
    now = int(time.time())
    conn.execute(
        """INSERT OR IGNORE INTO orders
           (id, external_id, invoice_id, amount_sat, payer_addr, status, txid, created_at, confirmed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            inv_id,
            invoice.get("external_id"),
            inv_id,
            invoice.get("amount_due_sat") or 0,
            invoice.get("address") or "",
            status,
            txid,
            invoice.get("created_at") or now,
            confirmed_at,
        ),
    )
    conn.execute(
        """UPDATE orders
           SET status=?, txid=?, confirmed_at=?, amount_sat=?, payer_addr=?
           WHERE id=?""",
        (
            status,
            txid,
            confirmed_at,
            invoice.get("amount_due_sat") or 0,
            invoice.get("address") or "",
            inv_id,
        ),
    )
    conn.commit()


def sign_message(message: str) -> dict:
    """#3: pivx-agent-kit sign-message — returns {address, message, signature}.

    The kit pretty-prints its JSON across multiple lines (verified live), so
    the whole stdout must be parsed — NOT line-by-line.
    """
    env = dict(os.environ)
    env["PIVX_AGENT"] = KIT_AGENT
    try:
        proc = subprocess.run(
            [KIT, "sign-message", message],
            capture_output=True, text=True, env=env, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        print(f"[sign] kit failed rc={proc.returncode}: {proc.stderr.strip()[:200]}")
        return {}
    out = proc.stdout.strip()
    if not out:
        return {}
    # 1) whole output; 2) last line; 3) last brace-balanced object
    candidates = [out]
    lines = out.splitlines()
    if lines:
        candidates.append(lines[-1])
    for cand in candidates:
        try:
            obj = json.loads(cand, strict=False)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("signature"):
            return obj
    start, end = out.rfind("{"), out.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(out[start:end + 1], strict=False)
        except Exception:
            return {}
        if isinstance(obj, dict) and obj.get("signature"):
            return obj
    return {}


def deliver(conn, invoice: dict, confirmed_at: int) -> dict:
    """#3: compose alert, hash the ALERT CONTENT, sign, run delivery hook (argv)."""
    ext = invoice.get("external_id") or "?"
    inv_id = invoice.get("id") or "?"
    alert = invoice.get("metadata") or {}
    alert_hash = hashlib.sha256(
        json.dumps(alert, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    message = f"{alert_hash}:{inv_id}:{confirmed_at}"
    sig = sign_message(message)
    signature = sig.get("signature", "")
    signer = sig.get("address", "")
    if signature:
        conn.execute(
            "UPDATE orders SET alert_hash=?, signature=?, signer_addr=? WHERE id=?",
            (alert_hash, signature, signer, inv_id),
        )
        conn.commit()
    payload = {
        "event": "fall_alert",
        "external_id": ext,
        "invoice_id": inv_id,
        "txid": payments_txid(invoice),
        "alert_hash": alert_hash,
        "message": message,
        "signature": signature,
        "signer_address": signer,
        "timestamp": int(confirmed_at),
    }
    if DELIVERY_CMD:
        run_delivery(payload)
    return payload


def run_delivery(payload: dict):
    """#4: argv exec only — DELIVERY_CMD is shlex-split, tokens substituted with
    .replace() (never str.format / shell=True on buyer-controlled strings)."""
    try:
        argv = shlex.split(DELIVERY_CMD)
    except ValueError as e:
        print(f"[delivery] unparseable DELIVERY_CMD: {e}")
        return
    substituted = []
    for tok in argv:
        for key in PLACEHOLDERS:
            tok = tok.replace("{" + key + "}", str(payload.get(key, "")))
        substituted.append(tok)
    print(f"[delivery] {' '.join(substituted)}")
    try:
        subprocess.run(substituted, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[delivery] hook failed: {e}")


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

        event_type = event.get("event_type", "?")
        invoice = event.get("invoice", {})
        inv_id = invoice.get("id") or "?"
        conn = ledger()

        # #2: delivery-id dedupe — a retry of the SAME event is skipped.
        if delivery_id:
            try:
                seen = conn.execute(
                    "SELECT 1 FROM webhook_deliveries WHERE delivery_id=?",
                    (delivery_id,),
                ).fetchone()
                if seen:
                    conn.close()
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"duplicate delivery")
                    return
                conn.execute(
                    "INSERT INTO webhook_deliveries (delivery_id, invoice_id, event_type, received_at) VALUES (?,?,?,?)",
                    (delivery_id, inv_id, event_type, int(time.time())),
                )
                conn.commit()
            except sqlite3.IntegrityError:  # concurrent duplicate
                conn.close()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"duplicate delivery")
                return

        upsert_order(conn, invoice)

        if event_type == "invoice.confirmed":
            confirmed_at = payment_confirmed_at(invoice) or int(time.time())
            payload = deliver(conn, invoice, confirmed_at)
            signed = "signed ✓" if payload["signature"] else "UNSIGNED ⚠️"
            tg(
                f"💚 PIVX alert order confirmed\ninvoice {inv_id}\n"
                f"external {payload['external_id']}\nhash {payload['alert_hash'][:16]}…\n{signed}"
            )
        elif event_type in ("invoice.expired", "invoice.cancelled"):
            tg(
                f"⏰ PIVX order {event_type}: {inv_id} "
                f"({invoice.get('external_id', '?')})"
            )
        conn.close()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt, *args):
        print("[webhook] " + (fmt % args))


def main():
    port = int(os.environ.get("PORT", "7475"))
    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"[merchant-webhook-receiver] listening 127.0.0.1:{port} (agent {KIT_AGENT})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
