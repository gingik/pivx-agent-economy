#!/usr/bin/env python3
"""verify_n8n_code.py — verify jsCode escape layers in n8n-task-workflow.json."""
import json
import sys

path = "config/n8n-task-workflow.json"
wf = json.load(open(path))
codes = [n["parameters"]["jsCode"] for n in wf["nodes"] if "jsCode" in n.get("parameters", {})]
if not codes:
    print("FAIL: no jsCode node found")
    sys.exit(1)
code = codes[0]
print("jsCode head repr:", repr(code[:120]))
seg = code.split("replace(")[1].split("]")[0]
print("regex segment repr:", repr(seg))
required = ["\\u0000", "\\u0008", "\\u000B", "\\u000C", "\\u000E", "\\u001F", "\\u007F"]
ok = all(r in code for r in required)
print("single-backslash JSON escapes present (valid JS regex):", ok)
sys.exit(0 if ok else 1)
