#!/usr/bin/env python3
"""produce-proof.py — standardize proof types and make them agent-native (item 5).

Takes a deliverable file (text note, downloaded artifact, screenshot, report)
and emits a machine-verifiable proof.json:

    {
      "type": "signed-text" | "hash" | "screenshot",
      "path": "<deliverable>",
      "hash": "<sha256 of deliverable>",
      "meta": { ...optional caller metadata... },
      "signed": {
        "message": "<hash>",
        "address": "<PIVX address>",
        "signature": "<base64>"
      }
    }

The signature is produced by `pivx-agent-kit sign-message <hash>` — verifiable
publicly with PIVX Core `verifymessage <address> <signature> <hash>`.

Usage:
  produce-proof.py <deliverable> --out <proof.json> [--type signed-text|hash|screenshot]
                   [--agent <name>] [--ledger <db>] [--task-id <id>]
                   [--meta '<json>'] [--no-sign]

Env: PIVX_AGENT (required when signing). Stdlib + subprocess only.

Prints the sha256 hash on stdout (single line) for callers.
"""
import hashlib
import json
import os
import subprocess
import sys

VALID_TYPES = ("signed-text", "hash", "screenshot")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_message(message: str) -> dict:
    """Sign via the pivx-agent-kit wrapper. Returns {address, message, signature}."""
    agent = os.environ.get("PIVX_AGENT", "")
    if not agent:
        raise RuntimeError("PIVX_AGENT not set; cannot sign")
    out = f"/tmp/produce_proof_sign_{abs(hash(message))}.json"
    # Redirect to a file first (repo rule: no pipes into interpreters for kit
    # output); parse the file afterwards.
    proc = subprocess.run(
        ["pivx-agent-kit", "sign-message", message],
        env={**os.environ, "PIVX_AGENT": agent},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout.decode("utf-8", "replace"))
    try:
        with open(out, "r", encoding="utf-8") as fh:
            data = json.load(fh, strict=False)
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"sign-message failed (rc={proc.returncode}): {exc}") from exc
    finally:
        try:
            os.remove(out)
        except OSError:
            pass
    if proc.returncode != 0 or "signature" not in data:
        raise RuntimeError(f"sign-message failed (rc={proc.returncode}): {data}")
    return {
        "message": str(data.get("message", message)),
        "address": str(data.get("address", "")),
        "signature": str(data.get("signature", "")),
    }


def journal_proof(ledger_db: str, agent: str, task_id: str, dpath: str,
                  ptype: str, phash: str, signature: str, signer_addr: str) -> None:
    subprocess.run(
        ["python3", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.py"),
         "journal-proof", ledger_db, agent, task_id, dpath, ptype, phash,
         signature or "", signer_addr or ""],
        check=True, timeout=60)


def main(argv: list) -> int:
    if len(argv) < 3:
        sys.stderr.write(__doc__)
        return 2
    deliverable, out_path = argv[0], None
    ptype, agent, ledger_db, task_id, meta, do_sign = "signed-text", None, None, None, {}, True
    i = 0
    args = list(argv)
    while i < len(args):
        a = args[i]
        if a == "--out":
            i += 1
            out_path = args[i]
        elif a == "--type":
            i += 1
            ptype = args[i]
        elif a == "--agent":
            i += 1
            agent = args[i]
        elif a == "--ledger":
            i += 1
            ledger_db = args[i]
        elif a == "--task-id":
            i += 1
            task_id = args[i]
        elif a == "--meta":
            i += 1
            meta = json.loads(args[i], strict=False)
        elif a == "--no-sign":
            do_sign = False
        elif a.startswith("-") and a != deliverable:
            sys.stderr.write(f"produce-proof.py: unknown option {a}\n")
            return 2
        i += 1
    if ptype not in VALID_TYPES:
        sys.stderr.write(f"produce-proof.py: bad --type {ptype}\n")
        return 2
    if not out_path:
        sys.stderr.write("produce-proof.py: --out required\n")
        return 2
    if not os.path.isfile(deliverable):
        sys.stderr.write(f"produce-proof.py: no such deliverable: {deliverable}\n")
        return 2

    phash = sha256_file(deliverable)
    signed = False
    if do_sign:
        try:
            signed = sign_message(phash)
        except RuntimeError as exc:
            print(f"produce-proof: WARNING signing skipped: {exc}", file=sys.stderr)
            signed = False

    proof = {
        "type": ptype,
        "path": deliverable,
        "hash": phash,
        "meta": meta,
        "signed": signed,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(proof, fh, indent=2)

    if ledger_db and agent and task_id:
        try:
            journal_proof(ledger_db, agent, task_id, deliverable, ptype, phash,
                          signed["signature"] if signed else "",
                          signed["address"] if signed else "")
        except subprocess.CalledProcessError as exc:
            print(f"produce-proof: WARNING ledger journal failed: {exc}", file=sys.stderr)

    print(phash)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
