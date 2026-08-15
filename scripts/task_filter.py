#!/usr/bin/env python3
"""task_filter.py — filter PIVX Tasks open-bounty list for unattended categories.

The kit's `task list` JSON contains raw control characters in descriptions, so
strict=False is required. Usage:
    pivx-agent-kit task list --status open --limit 50 > /tmp/list.json
    python3 task_filter.py /tmp/list.json 'dev|social|research|content'
Prints a JSON array of eligible tasks to stdout.
"""
import json
import re
import sys


def main():
    path, pattern = sys.argv[1], sys.argv[2]
    try:
        raw = open(path, encoding="utf-8").read()
        tasks = json.loads(raw, strict=False)
    except Exception as e:
        print(f"PARSE ERROR: {e}", file=sys.stderr)
        tasks = []
    cat = re.compile(pattern)
    out = [t for t in tasks if cat.search(str(t.get("category", "")))]
    print(json.dumps(out))


if __name__ == "__main__":
    main()
