#!/usr/bin/env python3
"""wallet-check.py — sanity-check a pivx-agent-kit wallet.json.

Replaces the inline heredoc in wallet-backup.sh (repo rule: no heredocs).

Usage: wallet-check.py <wallet.json>
Exit 0 = parses and is non-empty; exit 1 = missing/empty/invalid JSON.
"""
import json
import sys


def main(argv: list) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: wallet-check.py <wallet.json>\n")
        return 2
    path = argv[0]
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"ERROR: cannot read {path}: {e}")
        return 1
    if not raw.strip():
        print(f"ERROR: {path} is empty")
        return 1
    try:
        data = json.loads(raw)
    except ValueError as e:
        print(f"ERROR: {path} is not valid JSON: {e}")
        return 1
    if not isinstance(data, dict):
        print(f"ERROR: {path} parses but is not a JSON object")
        return 1
    print(f"OK: {path} parses ({len(raw)} bytes, {len(data)} top-level keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
