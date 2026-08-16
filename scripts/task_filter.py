#!/usr/bin/env python3
"""task_filter.py — filter eligible tasks from `pivx-agent-kit task list` output.

Modes:
  task_filter.py <list.json> <categories>          print filtered task array (JSON)
  task_filter.py pick <filtered.json> <max> <outdir>
      print "id<TAB>title<TAB>amount" lines (max) and dump each picked task's
      full JSON to <outdir>/task_<id>.json (used by task-runner.sh for the
      pre-signup capability guard — no shell pipes into interpreters).

Category match is exact membership in the pipe-separated categories string.
"""
import json
import os
import sys


def load_list(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh, strict=False)
    if isinstance(data, list):
        return data
    return data.get("items", []) if isinstance(data, dict) else []


def main(argv: list) -> int:
    if len(argv) == 2:
        list_json, categories = argv[0], argv[1]
        cats = set(categories.split("|"))
        items = [t for t in load_list(list_json) if t.get("category") in cats]
        print(json.dumps(items))
        return 0

    if len(argv) == 4 and argv[0] == "pick":
        filtered_json, max_n, outdir = argv[1], int(argv[2]), argv[3]
        os.makedirs(outdir, exist_ok=True)
        items = load_list(filtered_json)[:max_n]
        for t in items:
            tid = str(t.get("id", ""))
            with open(os.path.join(outdir, f"task_{tid}.json"), "w", encoding="utf-8") as fh:
                json.dump(t, fh)
            amt = t.get("quoted_amount", t.get("bounty_sat", t.get("amount", "")))
            print(f"{tid}\t{t.get('title','')[:80]}\t{amt}")
        return 0

    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
