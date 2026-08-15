#!/usr/bin/env python3
"""fix_n8n_code.py — set jsCode with byte-exact escape layers (no shell mangling).

Target state, layer by layer:
  FILE (JSON text):  "...replace(/[\\u0000-...]/g, ' ');\\nconst tasks = ..."
                     (double backslash before u — valid JSON escape for backslash)
  JSON.parse -> JS source: "...replace(/[\u0000-...]/g, ' ');\nconst tasks = ..."
                     (single backslash before u — valid JS regex escape)
"""
import json

BS = chr(92)  # backslash, immune to any quoting layer

REGEX = (
    "/[" + BS + "u0000-" + BS + "u0008" + BS + "u000B" + BS + "u000C"
    + BS + "u000E-" + BS + "u001F" + BS + "u007F]/g"
)

JS_SOURCE = (
    "const raw = String($input.first().json.stdout).replace(" + REGEX + ", ' ');"
    + "\nconst tasks = JSON.parse(raw);"
    + "\nconst eligible = tasks.filter(t => /dev|social|research|content/.test(String(t.category || '')));"
    + "\nreturn eligible.map(t => ({ json: { id: t.id, title: t.title, amount: t.amount, category: t.category } }));"
)

path = "config/n8n-task-workflow.json"
wf = json.load(open(path))
changed = 0
for node in wf["nodes"]:
    if "jsCode" in node.get("parameters", {}):
        node["parameters"]["jsCode"] = JS_SOURCE
        changed += 1
assert changed == 1, f"expected 1 jsCode node, found {changed}"
json.dump(wf, open(path, "w"), indent=2)

# ---- verify the exact layers ----
wf2 = json.load(open(path))
code = [n["parameters"]["jsCode"] for n in wf2["nodes"] if "jsCode" in n.get("parameters", {})][0]
assert BS + "u0000" in code, "jsCode must contain backslash-u0000 escape text"
assert BS + BS not in code, "no double-backslash sequences (wrong layer)"
assert "\x00" not in code and "\x07" not in code, "no raw control bytes"
# the file on disk must double-escape (JSON layer) so JSON.parse yields single
raw_text = open(path, encoding="utf-8").read()
assert "\\\\u0000" in raw_text, "file JSON text must have double backslashes"
print("OK: jsCode escape layers verified")
print(repr(code[:100]))
