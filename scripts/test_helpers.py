#!/usr/bin/env python3
"""test_helpers.py — quick checks for pivutil.py, ledger.py, verify-addresses.py,
wallet-check.py. Stdlib only, temp DB, no network."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def run_py(args, stdin=None):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, input=stdin)


def main():
    print("== helper tests ==")

    # ---- pivutil: Decimal exactness (bug #8) ----
    r = run_py([os.path.join(HERE, "pivutil.py"), "piv-to-sat", "123.45678901"])
    check("piv-to-sat exact (123.45678901)", r.stdout.strip() == "12345678901", r.stdout)
    r = run_py([os.path.join(HERE, "pivutil.py"), "piv-to-sat", "0.00000001"])
    check("piv-to-sat 1 sat", r.stdout.strip() == "1", r.stdout)
    r = run_py([os.path.join(HERE, "pivutil.py"), "piv-to-sat", "999999999.99999999"])
    check("piv-to-sat large exact", r.stdout.strip() == "99999999999999999", r.stdout)
    bal = json.dumps({"public_balance": "12.34567890", "private_balance": "0.00000001"})
    r = run_py([os.path.join(HERE, "pivutil.py"), "balance-to-sat"], stdin=bal)
    check("balance-to-sat sum exact", r.stdout.strip() == "1234567891", r.stdout)
    # raw control char in JSON (kit quirk) must not break strict=False parsing
    r = run_py([os.path.join(HERE, "pivutil.py"), "balance-to-sat"],
               stdin='{"public_balance": "1.5", "private_balance": "0.5", "note": "a\x01b"}')
    check("balance-to-sat handles raw control chars", r.stdout.strip() == "200000000", r.stdout)

    # ---- ledger.py subcommands ----
    db = os.path.join(tempfile.mkdtemp(), "ledger.db")
    r = run_py([os.path.join(HERE, "ledger.py"), "init-schema", db])
    check("ledger init-schema", r.returncode == 0)
    r = run_py([os.path.join(HERE, "ledger.py"), "count-signed-up", db, "hermes-main"])
    check("count-signed-up starts 0", r.stdout.strip() == "0", r.stdout)
    # pre-inserted gate rows must NOT count (bug #6)
    for status in ("applied", "pending-approval"):
        run_py([os.path.join(HERE, "ledger.py"), "journal-task", db, "hermes-main",
                "t1", status, "gate", "1000"])
    r = run_py([os.path.join(HERE, "ledger.py"), "count-signed-up", db, "hermes-main"])
    check("gate rows do not open the gate (#6)", r.stdout.strip() == "0", r.stdout)
    for status in ("signed-up", "submitted", "approved", "paid", "disputed"):
        run_py([os.path.join(HERE, "ledger.py"), "journal-task", db, "hermes-main",
                "t1", status, "", "2000"])
    r = run_py([os.path.join(HERE, "ledger.py"), "count-signed-up", db, "hermes-main"])
    check("real progress counts (#6)", r.stdout.strip() == "5", r.stdout)
    # spend journal + spent-today window
    run_py([os.path.join(HERE, "ledger.py"), "journal-spend", db, "hermes-main",
            "1000000", "50000000", "allowed"])
    run_py([os.path.join(HERE, "ledger.py"), "journal-spend", db, "hermes-main",
            "1000000", "30000000", "denied"])
    r = run_py([os.path.join(HERE, "ledger.py"), "spent-today", db, "1086400"])
    check("spent-today sums only allowed", r.stdout.strip() == "50000000", r.stdout)

    # ---- verify-addresses.py (uses real agent addresses) ----
    real_out = json.dumps({
        "shield_address": "ps1hpamhcrgumpt2lq6hh60y4522d986n44ktgd5jxqzge5ll8kdxfm53ne8he0c7cpajvk7gfstjq",
        "transparent_address": "DEd1j7RYyu8RVxLbBV4swKS3abwYQsyVoi"})
    r = run_py([os.path.join(HERE, "verify-addresses.py"), "hermes-main"], stdin=real_out)
    check("verify-addresses PASS on match", r.returncode == 0 and "RESULT: PASS" in r.stdout,
          r.stdout[-200:])
    bad = json.dumps({"shield_address": "ps1wrong", "transparent_address": "Dwrong"})
    r = run_py([os.path.join(HERE, "verify-addresses.py"), "hermes-main"], stdin=bad)
    check("verify-addresses FAIL on mismatch", r.returncode == 1 and "RESULT: FAIL" in r.stdout,
          r.stdout[-200:])

    # ---- wallet-check.py against the real wallet file ----
    wallet = os.path.expanduser("~/.local/share/pivx-agent-kit/hermes-main/wallet.json")
    if os.path.isfile(wallet):
        r = run_py([os.path.join(HERE, "wallet-check.py"), wallet])
        check("wallet-check parses live wallet", r.returncode == 0 and "OK" in r.stdout,
              r.stdout[-100:])

    # ---- canary-scan: --list mode ----
    r = run_py([os.path.join(HERE, "canary-scan.py"), "--list"])
    check("canary-scan --list runs", r.returncode in (0, 2))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
