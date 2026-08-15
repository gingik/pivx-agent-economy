#!/usr/bin/env python3
"""test_receiver.py — regression test for merchant-webhook-receiver.py.

Covers the 2026-08-15 bug list:
  #1 txid comes from invoice["payments"][0]["txid"], not invoice["txid"]
  #2 delivery-id dedupe (retry of same event skipped) + status transitions
     (pending -> confirmed UPDATE the row instead of INSERT-OR-IGNORE)
  #3 sign-message wiring: signature + signer_addr stored on the row
  #4 DELIVERY_CMD runs as argv list — shell metacharacters in external_id
     are inert (no command injection)

Run: python3 scripts/test_receiver.py   (stdlib only, no network beyond loopback)
"""
import hashlib
import hmac
import http.client
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time

# env must be set BEFORE the module is imported (module constants read at exec)
_TMPDIR = tempfile.mkdtemp()
os.environ["LEDGER_DB"] = os.path.join(_TMPDIR, "ledger.db")
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["PIVX_AGENT"] = "hermes-main"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# hyphenated filename: load via importlib instead of `import`
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location(
    "mwr", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "merchant-webhook-receiver.py"))
recv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recv)  # noqa: E402

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


def make_invoice(inv_id="inv-1", status="pending", txid=None, external="alert-1"):
    payments = []
    if txid:
        payments.append({"txid": txid, "vout": 0, "amount_sat": 1000,
                         "confirmations": 0, "seen_at": 100, "confirmed_at": None})
    return {
        "id": inv_id,
        "external_id": external,
        "channel": "transparent",
        "amount_due_sat": 1000,
        "amount_paid_sat": 0,
        "address": "D1111111111111111111111111111111111111",
        "status": status,
        "created_at": 100,
        "expires_at": 100 + 1800,
        "refund_address": None,
        "metadata": {"alert": {"sensor": "lol-in-1", "event": "fall", "ts": 123}},
        "payments": payments,
    }


def hmac_headers(body: bytes, delivery_id: str, event_type: str) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Merchant-Delivery-Id": delivery_id,
        "X-Merchant-Event-Type": event_type,
        "X-Merchant-Signature": hmac.new(b"test-secret", body, hashlib.sha256).hexdigest(),
    }


def main():
    print("== receiver regression tests ==")
    db = recv.LEDGER_DB  # same DB the module writes to (env set pre-import)

    # ---- #1 txid extraction ----
    inv = make_invoice(txid="abc123def456")
    check("#1 payments[0].txid extracted", recv.payments_txid(inv) == "abc123def456")
    check("#1 empty payments -> ''", recv.payments_txid(make_invoice()) == "")

    # ---- HMAC verify ----
    body = b'{"a": 1}'
    good = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    check("hmac valid passes", recv.verify(body, good))
    check("hmac tampered fails", not recv.verify(body, hmac.new(b"wrong", body, hashlib.sha256).hexdigest()))
    check("hmac missing header fails", not recv.verify(body, ""))

    # ---- #2 dedupe + transitions via real HTTP server ----
    srv = recv.http.server.HTTPServer(("127.0.0.1", 0), recv.Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def post(delivery_id, event_type, invoice):
        raw = json.dumps({"event_id": "evt-" + delivery_id, "event_type": event_type,
                          "created_at": time.time(), "invoice": invoice}).encode()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/webhook", body=raw, headers=hmac_headers(raw, delivery_id, event_type))
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    # pending event, first delivery
    status = post("d-1", "invoice.confirmed", make_invoice(txid="tx1"))
    check("#2 pending delivery accepted", status == 200)
    # duplicate retry of the SAME delivery id must be skipped
    status = post("d-1", "invoice.confirmed", make_invoice(txid="tx1"))
    check("#2 duplicate delivery-id skipped", status == 200)

    # ---- status transition: confirmed event (new delivery id) updates the row ----
    confirmed = make_invoice(status="confirmed", txid="tx1")
    confirmed["payments"] = [{"txid": "tx1", "vout": 0, "amount_sat": 1000,
                              "confirmations": 3, "seen_at": 100,
                              "confirmed_at": 150}]
    post("d-2", "invoice.confirmed", confirmed)

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT status, txid, confirmed_at FROM orders WHERE id='inv-1'").fetchone()
    check("#2 transition pending->confirmed", row and row[0] == "confirmed", f"got {row}")
    check("#2 txid persisted", row and row[1] == "tx1")
    check("#2 confirmed_at persisted", row and row[2] == 150)

    # ---- #3 signature flow ----
    sig_row = conn.execute(
        "SELECT alert_hash, signature, signer_addr FROM orders WHERE id='inv-1'").fetchone()
    check("#3 alert_hash stored", bool(sig_row and sig_row[0]))
    # signature: non-empty, base64-ish (alnum + / + =)
    import re as _re
    _sig_ok = bool(sig_row and sig_row[1] and len(sig_row[1]) > 20
                   and _re.fullmatch(r"[A-Za-z0-9+/=]+", sig_row[1]))
    check("#3 signature stored (base64-ish)", _sig_ok)
    check("#3 signer_addr stored", sig_row and sig_row[2] == "DEd1j7RYyu8RVxLbBV4swKS3abwYQsyVoi")
    check("#3 hash is over alert content, not invoice envelope",
          sig_row and sig_row[0] == hashlib.sha256(
              json.dumps(confirmed["metadata"], sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    # ---- deliveries table recorded both events ----
    n_deliv = conn.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0]
    check("#2 deliveries recorded (d-1,d-2)", n_deliv == 2, f"got {n_deliv}")
    conn.close()

    # ---- #4 command injection: DELIVERY_CMD argv exec ----
    evil = "evil; rm -rf /tmp/PWNED ; touch /tmp/PWNED"
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = '{\n  "address": "DEd1j7RYyu8RVxLbBV4swKS3abwYQsyVoi",\n  "message": "x",\n  "signature": "AAAA/BBBB==="\n}\n'
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return FakeProc()

    recv.DELIVERY_CMD = "/bin/echo {external_id} {signature}"
    recv.subprocess.run = fake_run
    recv.deliver(recv.ledger(), make_invoice(txid="tx2", external=evil), 150)
    argv = captured.get("argv", [])
    check("#4 delivery argv is a list", isinstance(argv, list))
    check("#4 semicolon stays literal data (no shell)",
          argv[:2] == ["/bin/echo", evil], f"got {argv[:2]}")
    check("#4 no /tmp/PWNED created", not os.path.exists("/tmp/PWNED"))

    # ---- HMAC-missing event rejected ----
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    raw = json.dumps({"event_type": "invoice.confirmed", "invoice": make_invoice("inv-9")}).encode()
    c.request("POST", "/webhook", body=raw,
              headers={"Content-Type": "application/json", "X-Merchant-Delivery-Id": "d-9"})
    r = c.getresponse()
    r.read()
    c.close()
    check("#hmac 401 without signature", r.status == 401)

    srv.shutdown()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
