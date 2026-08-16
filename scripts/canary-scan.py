#!/usr/bin/env python3
"""canary-scan.py — T5 canary: scan logs for seed-phrase fragments.

Security checklist / test-plan T5 require a canary: grep all logs for mnemonic
fragments, so an accidental seed leak (hermes session logs, /tmp, kit dirs,
n8n output) is caught early instead of silently. This script implements it.

Setup (one-time, Kon runs — the words come from his paper seed):
  1. Pick 3-4 NON-ADJACENT words from the 24-word seed (e.g. words #4, #11,
     #19). 3/24 words cannot steal funds, so storing them is safe.
  2. mkdir -p ~/.config/pivx-agent-economy
  3. chmod 600 ~/.config/pivx-agent-economy/canary-words.txt
     one word per line, '#' comments allowed. NEVER commit this file.
  4. Run this script; wire into cron (e.g. daily) if desired.

Detection rule: a file is reported only if it contains >= 2 DISTINCT canary
words (word-boundary match). One shared word like 'table' is a false positive
on its own; two different seed words in the same file = leak confidence.

Exit: 0 = clean, 1 = hits (cron-friendly alert). --list shows config state.
"""
import argparse
import os
import re
import sys

CANARY_FILE = os.path.expanduser("~/.config/pivx-agent-economy/canary-words.txt")
SCAN_DIRS = [
    os.path.expanduser("~/.hermes"),        # session/transcript logs
    "/tmp",                                 # anything dropped there
    os.path.expanduser("~/.local/share/pivx-agent-kit"),  # wallet dirs + ledger
]
MAX_FILE_BYTES = 50_000_000


def load_words():
    if not os.path.isfile(CANARY_FILE):
        return []
    words = []
    for line in open(CANARY_FILE, encoding="utf-8"):
        w = line.strip().lower()
        if w and not w.startswith("#"):
            words.append(w)
    return words


def scan(words):
    """Return {file_path: [matched_words]} for files with >= 2 distinct words."""
    patterns = [re.compile(rf"\b{re.escape(w)}\b") for w in words]
    hits = {}
    for base in SCAN_DIRS:
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fname in files:
                path = os.path.join(root, fname)
                try:
                    if os.path.getsize(path) > MAX_FILE_BYTES:
                        continue
                    with open(path, encoding="utf-8", errors="ignore") as fh:
                        text = fh.read().lower()
                except OSError:
                    continue
                found = [words[i] for i, pat in enumerate(patterns) if pat.search(text)]
                if len(found) >= 2:
                    hits[path] = found
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="show config state and exit")
    args = ap.parse_args()

    words = load_words()
    if args.list:
        print(f"canary file: {CANARY_FILE}")
        print(f"words configured: {len(words)}")
        print("scan dirs:")
        for d in SCAN_DIRS:
            print(f"  {d}  {'(present)' if os.path.isdir(d) else '(absent)'}")
        if not words:
            print("NO CANARY WORDS CONFIGURED — see script header for setup")
        return 0 if words else 2

    if not words:
        print("canary-scan: no canary-words.txt — see header (setup step)")
        return 2

    hits = scan(words)
    if not hits:
        print(f"canary-scan: CLEAN ({len(words)} words, {len(SCAN_DIRS)} dirs)")
        return 0
    for path, found in sorted(hits.items()):
        print(f"LEAK SUSPECTED: {path}")
        print(f"  matched words: {', '.join(found)}")
    print("ACTION: inspect the file; if the seed leaked, rotate the wallet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
