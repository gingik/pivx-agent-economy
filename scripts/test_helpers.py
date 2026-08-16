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

    # ---- ledger migration (old schema → proof/introspection columns) ----
    olddb = os.path.join(tempfile.mkdtemp(), "old.db")
    oc = sqlite3.connect(olddb)
    oc.execute("""CREATE TABLE task_rewards (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
        handle TEXT NOT NULL, bounty_sat INTEGER, status TEXT NOT NULL DEFAULT 'applied',
        txid TEXT, reason TEXT, ts INTEGER NOT NULL)""")
    oc.execute("INSERT INTO task_rewards (task_id, handle, status, ts) VALUES ('t9', 'hermes-main', 'signed-up', 3000)")
    oc.commit(); oc.close()
    r = run_py([os.path.join(HERE, "ledger.py"), "init-schema", olddb])
    check("ledger migration runs on old schema", r.returncode == 0, r.stdout + r.stderr)
    oc = sqlite3.connect(olddb)
    cols = {d[1] for d in oc.execute("PRAGMA table_info(task_rewards)")}
    oc.close()
    for col in ("task_title", "category", "verification", "deliverable_path",
                "proof_type", "proof_hash", "signature", "signer_addr"):
        check(f"migration adds column {col}", col in cols)

    # introspect-task-file: journal fields from a saved `task get` JSON
    tj = os.path.join(tempfile.mkdtemp(), "task-88.json")
    with open(tj, "w") as fh:
        json.dump({"id": 88, "title": "Download Edge Wallet",
                   "category": "marketing",
                   "description": "get the app", "verification": "hash + note"}, fh)
    r = run_py([os.path.join(HERE, "ledger.py"), "introspect-task-file", olddb, "hermes-main", tj])
    check("introspect-task-file runs", r.returncode == 0, r.stdout + r.stderr)
    r = run_py([os.path.join(HERE, "ledger.py"), "latest", olddb, "hermes-main", "88"])
    row = json.loads(r.stdout)
    check("introspect journals title", row.get("task_title") == "Download Edge Wallet", r.stdout)
    check("introspect journals category", row.get("category") == "marketing")
    check("introspect journals verification", row.get("verification") == "hash + note")

    # journal-proof + journal-reward-txid + inflight
    r = run_py([os.path.join(HERE, "ledger.py"), "journal-proof", olddb, "hermes-main", "88",
                "deliverable-88.txt", "signed-text", "abc123", "SIG", "Daddr"])
    check("journal-proof runs", r.returncode == 0, r.stdout + r.stderr)
    r = run_py([os.path.join(HERE, "ledger.py"), "latest", olddb, "hermes-main", "88"])
    row = json.loads(r.stdout)
    check("proof metadata on latest row", row.get("deliverable_path") == "deliverable-88.txt"
          and row.get("proof_type") == "signed-text" and row.get("signer_addr") == "Daddr", r.stdout)
    r = run_py([os.path.join(HERE, "ledger.py"), "journal-reward-txid", olddb, "hermes-main", "88", "feedface"])
    check("journal-reward-txid runs", r.returncode == 0, r.stdout + r.stderr)
    r = run_py([os.path.join(HERE, "ledger.py"), "inflight", olddb, "hermes-main"])
    inflight = json.loads(r.stdout)
    check("inflight lists still-open task t9", any(x["task_id"] == "t9" for x in inflight), r.stdout)
    check("inflight excludes settled task (paid-txid)", not any(x["task_id"] == "88" for x in inflight), r.stdout)

    # ---- work-dispatcher routing (importlib — hyphenated filename) ----
    import importlib.util
    spec = importlib.util.spec_from_file_location("dispatcher", os.path.join(HERE, "work-dispatcher.py"))
    dispatcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(dispatcher)
    def route_for(title, desc, cat):
        return dispatcher.route({"title": title, "description": desc, "category": cat})
    check("route download (edge/wallet)", route_for("Download Edge Wallet", "install the app", "marketing") == "download")
    check("route social (discord)", route_for("Join the PIVX Discord", "follow and say hi", "social") == "social")
    check("route research", route_for("Research PIVX governance", "analyze and summarize with sources", "research") == "research")
    check("route content", route_for("Write an article", "content for the blog", "content") == "content")
    check("route fallback monitoring", route_for("Watch the daemon", "keep node healthy", "dev") == "monitoring")

    # --check honors the capability matrix (social disabled → rc 3)
    matrix = os.path.join(HERE, "..", "config", "agent-capabilities.json")
    td = tempfile.mkdtemp()
    soc = os.path.join(td, "soc.json")
    with open(soc, "w") as fh:
        json.dump({"id": 1, "title": "Join the PIVX Discord", "description": "join", "category": "social"}, fh)
    dl = os.path.join(td, "dl.json")
    with open(dl, "w") as fh:
        json.dump({"id": 2, "title": "Download Edge Wallet", "description": "get it", "category": "marketing"}, fh)
    r = run_py([os.path.join(HERE, "work-dispatcher.py"), "--check", soc, "--matrix", matrix])
    check("--check SKIPs disabled template (rc 3)", r.returncode == 3, f"rc={r.returncode} {r.stdout}")
    r = run_py([os.path.join(HERE, "work-dispatcher.py"), "--check", dl, "--matrix", matrix])
    check("--check OK enabled template (rc 0)", r.returncode == 0, f"rc={r.returncode} {r.stdout}")

    # ---- produce-proof (no wallet: --no-sign) ----
    dlf = os.path.join(td, "note.txt")
    with open(dlf, "w") as fh:
        fh.write("task 9 work note\n")
    pf = os.path.join(td, "proof.json")
    r = run_py([os.path.join(HERE, "produce-proof.py"), dlf, "--out", pf, "--type", "signed-text", "--no-sign"])
    check("produce-proof runs unsigned", r.returncode == 0, r.stdout + r.stderr)
    with open(pf) as fh:
        proof = json.load(fh)
    check("proof type + path", proof["type"] == "signed-text" and proof["path"] == dlf)
    check("proof hash is sha256 of file", len(proof["hash"]) == 64 and proof["signed"] is False)

    # ---- task-status-watch parsing (importlib) ----
    spec = importlib.util.spec_from_file_location("tsw", os.path.join(HERE, "task-status-watch.py"))
    tsw = importlib.util.module_from_spec(spec); spec.loader.exec_module(tsw)
    check("watch: approved mapping", tsw.status_from_message("Your submission was approved") == "approved")
    check("watch: rejected mapping", tsw.status_from_message("Submission rejected: blurry") == "rejected")
    check("watch: paid mapping (payment sent)", tsw.status_from_message("Payment of 2.0 PIV sent to your wallet") == "paid")
    check("watch: txid extraction",
          tsw.find_txid("paid txid=bb8bfeaa3ee231ec52a233fafb49b3c9b57f40334474303cd5d4f577da06bc67")
          == "bb8bfeaa3ee231ec52a233fafb49b3c9b57f40334474303cd5d4f577da06bc67")
    check("watch: txid none", tsw.find_txid("no tx here") == "")

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
