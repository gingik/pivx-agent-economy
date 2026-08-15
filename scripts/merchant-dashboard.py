#!/usr/bin/env python3
"""
merchant-dashboard — live status page for the PIVX agent-to-agent merchant.

Single Flask page (port 5030, HTTP Basic auth) showing:
  * daemon health (/healthz) + chain tip (public RPC, best-effort)
  * agent wallet balance (pivx-agent-kit balance, cached 60s)
  * invoices + payments straight from the merchant SQLite DB
    (docker cp db+wal+shm to a cache dir — single-file copies miss
    live WAL writes; copy all three together)
  * webhook deliveries from the receiver ledger
  * tail of the daemon log

Run:
    ./venv/bin/python scripts/merchant-dashboard.py [--port 5030]

Auth: HTTP Basic via MERCHANT_DASH_USER / MERCHANT_DASH_PASS
(env, falling back to ~/.hermes/.env — same pattern as coldcard-dashboard).
"""
import argparse
import os
import re
import sqlite3
import subprocess
import time
import urllib.request
from datetime import datetime

from flask import Flask, Response, render_template_string, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
ENV_FILE = os.path.expanduser("~/.hermes/.env")
DB_CACHE = "/tmp/merchant-dash-cache"
LEDGER = os.path.expanduser("~/.local/share/pivx-agent-kit/ledger.db")
AGENT_KIT = os.path.expanduser("~/.local/bin/pivx-agent-kit")
RPC = "https://rpc.pivxla.bz/mainnet"
EXPLORER = "https://explorer.pivxla.bz"
DB_COPY_MAX_AGE = 15  # seconds between docker cp refreshes
BALANCE_MAX_AGE = 60

app = Flask(__name__)


def _env_or_dotenv(name, default=""):
    val = os.environ.get(name, "")
    if val:
        return val
    try:
        with open(ENV_FILE) as f:
            for line in f:
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return default


AUTH_USER = _env_or_dotenv("MERCHANT_DASH_USER", "")
AUTH_PASS = _env_or_dotenv("MERCHANT_DASH_PASS", "")


@app.before_request
def require_auth():
    if not AUTH_PASS:
        return None  # dev mode, open
    auth = request.authorization
    ok = (
        auth is not None
        and auth.username == AUTH_USER
        and auth.password == AUTH_PASS
    )
    if not ok:
        return Response(
            "Authentication required",
            401,
            {"WWW-Authenticate": 'Basic realm="PIVX Merchant Dashboard"'},
        )
    return None


# ---------------------------------------------------------------- data bits
def _copy_db():
    """docker cp db + -wal + -shm together (WAL rule). Cached."""
    os.makedirs(DB_CACHE, exist_ok=True)
    dbp = os.path.join(DB_CACHE, "merchant.db")
    try:
        if time.time() - os.path.getmtime(dbp) < DB_COPY_MAX_AGE:
            return True
    except OSError:
        pass
    for f in ("merchant.db", "merchant.db-wal", "merchant.db-shm"):
        subprocess.run(
            ["docker", "cp", f"pivx-merchant:/app/data/{f}", DB_CACHE],
            capture_output=True,
        )
    return os.path.exists(dbp)


def _ro_conn(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _query(db_file, sql, args=()):
    conn = _ro_conn(db_file)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _piv(sat):
    return f"{sat / 1e8:.8f}" if sat is not None else "-"


def _ts(epoch):
    return (
        datetime.fromtimestamp(epoch).strftime("%d %b %H:%M:%S") if epoch else "-"
    )


def _health():
    try:
        with urllib.request.urlopen("http://127.0.0.1:7474/healthz", timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def _chain_tip():
    body = (
        '{"jsonrpc":"2.0","id":1,"method":"getblockcount","params":[]}'
    ).encode()
    req = urllib.request.Request(
        RPC, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.json()["result"]
    except Exception:
        return None


_balance_cache = (0.0, None)


def _balance():
    global _balance_cache
    now = time.time()
    if now - _balance_cache[0] < BALANCE_MAX_AGE:
        return _balance_cache[1]
    try:
        out = subprocess.run(
            [AGENT_KIT, "balance"], capture_output=True, text=True, timeout=25
        ).stdout.strip()
        m = re.search(r"([\d.]+)\s*PIV", out)
        _balance_cache = (now, out)
        return out
    except Exception as e:
        _balance_cache = (now, f"unavailable ({type(e).__name__})")
        return _balance_cache[1]


def _daemon_log():
    try:
        out = subprocess.run(
            ["docker", "logs", "--tail", "40", "pivx-merchant"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        return "\n".join(out.strip().splitlines()[-15:])
    except Exception:
        return "unavailable"


# ------------------------------------------------------------------- page
PAGE = """
<!doctype html>
<html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>PIVX Merchant</title>
<style>
 body{background:#111;color:#ddd;font:13px/1.5 ui-monospace,monospace;margin:20px}
 h1{font-size:18px;color:#f5b301}
 h2{font-size:14px;color:#8be28b;border-bottom:1px solid #333;margin-top:26px}
 .cards{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0}
 .card{background:#1a1a1a;border:1px solid #333;border-radius:6px;padding:10px 14px;min-width:150px}
 .card b{display:block;color:#999;font-size:11px;text-transform:uppercase}
 .card span{font-size:17px}
 .ok{color:#4caf50}.bad{color:#f44336}.warn{color:#f5b301}
 table{border-collapse:collapse;width:100%;margin:8px 0}
 th,td{text-align:left;padding:4px 10px;border-bottom:1px solid #262626;white-space:nowrap}
 th{color:#999;font-size:11px;text-transform:uppercase}
 a{color:#7cb3ff;text-decoration:none}
 .small{color:#777;font-size:11px}
 pre{background:#0d0d0d;border:1px solid #262626;border-radius:6px;padding:10px;
     overflow-x:auto;font-size:11.5px;color:#bbb}
</style></head><body>
<h1>PIVX Merchant — agent-to-agent payments</h1>
<div class="small">refreshes every 30s · updated {{ updated_at }}</div>
<div class="cards">
 <div class="card"><b>Daemon</b><span class="{{ 'ok' if health else 'bad' }}">
   {{ 'UP' if health else 'DOWN' }}</span></div>
 <div class="card"><b>Chain tip</b><span>{{ tip or '-' }}</span></div>
 <div class="card"><b>Wallet (hermes-main)</b><span class="small">{{ balance }}</span></div>
 <div class="card"><b>Invoices</b><span>{{ invoices|length }}</span></div>
 <div class="card"><b>Payments</b><span>{{ payments|length }}</span></div>
 <div class="card"><b>Webhooks</b><span>{{ webhooks|length }}</span></div>
</div>

<h2>Invoices</h2>
{% if invoices %}
<table><tr><th>id</th><th>ext</th><th>status</th><th>due (PIV)</th>
<th>address</th><th>created</th><th>expires</th></tr>
{% for i in invoices %}
<tr><td>{{ i.id[:8] }}</td><td>{{ i.external_id or '-' }}</td>
<td>{{ i.status }}</td><td>{{ piv(i.amount_due_sat) }}</td>
<td><a href="{{ EXPLORER }}/address/{{ i.address }}">{{ i.address[:14] }}…</a></td>
<td>{{ ts_fmt(i.created_at) }}</td><td>{{ ts_fmt(i.expires_at) }}</td></tr>
{% endfor %}</table>
{% else %}<div class="small">none</div>{% endif %}

<h2>Payments</h2>
{% if payments %}
<table><tr><th>txid</th><th>amount (PIV)</th><th>height</th>
<th>confs</th><th>invoice</th><th>seen</th></tr>
{% for p in payments %}
<tr><td><a href="{{ EXPLORER }}/tx/{{ p.txid }}">{{ p.txid[:16] }}…</a></td>
<td>{{ piv(p.amount_sat) }}</td><td>{{ p.block_height or 'mempool' }}</td>
<td>{{ p.confirmations }}</td><td>{{ p.invoice_id[:8] }}</td>
<td>{{ ts_fmt(p.seen_at) }}</td></tr>
{% endfor %}</table>
{% else %}<div class="small">none</div>{% endif %}

<h2>Webhook deliveries (receiver ledger)</h2>
{% if webhooks %}
<table><tr><th>delivery</th><th>invoice</th><th>event</th><th>received</th></tr>
{% for w in webhooks %}
<tr><td>{{ w.delivery_id[:8] }}</td><td>{{ w.invoice_id[:8] }}</td>
<td>{{ w.event_type }}</td><td>{{ ts_fmt(w.received_at) }}</td></tr>
{% endfor %}</table>
{% else %}<div class="small">none yet</div>{% endif %}

<h2>Daemon log (tail)</h2>
<pre>{{ log }}</pre>
</body></html>
"""


@app.route("/")
def index():
    now = int(time.time())
    health = _health()
    if _copy_db():
        try:
            invoices = _query(
                os.path.join(DB_CACHE, "merchant.db"),
                "SELECT id, external_id, status, amount_due_sat, address,"
                " created_at, expires_at FROM invoices ORDER BY created_at DESC",
            )
        except Exception:
            invoices = []
        try:
            payments = _query(
                os.path.join(DB_CACHE, "merchant.db"),
                "SELECT txid, amount_sat, block_height, confirmations,"
                " invoice_id, seen_at FROM payments ORDER BY seen_at DESC",
            )
        except Exception:
            payments = []
    else:
        invoices, payments = [], []
    try:
        webhooks = _query(
            LEDGER,
            "SELECT delivery_id, invoice_id, event_type, received_at"
            " FROM webhook_deliveries ORDER BY received_at DESC LIMIT 10",
        )
    except Exception:
        webhooks = []
    return render_template_string(
        PAGE,
        updated_at=now,
        health=health,
        tip=_chain_tip(),
        balance=_balance(),
        invoices=invoices,
        payments=payments,
        webhooks=webhooks,
        log=_daemon_log(),
        piv=_piv,
        ts_fmt=_ts,
        EXPLORER=EXPLORER,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5030)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    app.run(host=args.bind, port=args.port)
