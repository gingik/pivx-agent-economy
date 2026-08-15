#!/usr/bin/env python3
"""test_canary.py — functional test of canary-scan.py detection logic."""
import importlib.util
import os
import sys
import tempfile

spec = importlib.util.spec_from_file_location(
    "canary_scan", os.path.join(os.path.dirname(os.path.abspath(__file__)), "canary-scan.py"))
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def main():
    print("== canary-scan functional test ==")
    tmp = tempfile.mkdtemp()
    leak = os.path.join(tmp, "leak.log")
    benign = os.path.join(tmp, "benign.log")
    with open(leak, "w") as f:
        f.write("session dump: my seed has word alpha and word zulu somewhere\n")
    with open(benign, "w") as f:
        f.write("just one shared word: alpha is common in logs\n")

    old_dirs = cs.SCAN_DIRS[:]
    cs.SCAN_DIRS = [tmp]
    try:
        hits = cs.scan(["alpha", "zulu", "xylophone"])
        check("2 words in one file detected", leak in hits and hits[leak] == ["alpha", "zulu"],
              str(hits))
        check("1 word alone not reported", benign not in hits)
        hits2 = cs.scan(["xylophone"])
        check("no words -> clean", hits2 == {})
        # word-boundary: 'alphabet' must not match 'alpha'
        with open(os.path.join(tmp, "boundary.log"), "w") as f:
            f.write("alphabet soup zulu pie\n")
        hits3 = cs.scan(["alpha", "zulu"])
        check("word boundary respected", os.path.join(tmp, "boundary.log") not in hits3)
    finally:
        cs.SCAN_DIRS = old_dirs

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
