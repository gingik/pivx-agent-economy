#!/usr/bin/env python3
"""verify-addresses.py — compare recovered wallet addresses against agents.json.

Used by wallet-recover.sh to prove a paper-seed recovery produced the SAME
addresses as the live wallet (recovery drill pass criteria). Replaces the
inline heredoc (repo rule: no heredocs).

Usage:
  PIVX_AGENT=<agent> pivx-agent-kit address | verify-addresses.py <agent>
  PIVX_AGENT=<recovered> pivx-agent-kit address | verify-addresses.py <verify-agent>

Reads the `pivx-agent-kit address` JSON from stdin, loads config/agents.json
(relative to this script), and compares shield + transparent addresses with the
named agent's entry. Prints a side-by-side table.

Exit: 0 = both match, 1 = mismatch, 2 = config/input error.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS_JSON = os.path.join(HERE, "..", "config", "agents.json")


def main(argv) -> int:
    if len(argv) < 1:
        sys.stderr.write("usage: verify-addresses.py <agent-name>  (address JSON on stdin)\n")
        return 2
    agent_name = argv[0]

    try:
        raw = sys.stdin.read()
        recovered = json.loads(raw)
    except Exception as e:
        print(f"ERROR: cannot parse address JSON from stdin: {e}")
        return 2
    got_shield = recovered.get("shield_address") or ""
    got_transparent = recovered.get("transparent_address") or ""

    try:
        agents = json.load(open(AGENTS_JSON))["agents"]
    except Exception as e:
        print(f"ERROR: cannot load {AGENTS_JSON}: {e}")
        return 2
    entry = next((a for a in agents if a.get("name") == agent_name), None)
    if not entry:
        print(f"WARN: agent '{agent_name}' not in agents.json — update it manually.")
        return 2

    exp_shield = entry.get("shield_address") or ""
    exp_transparent = entry.get("transparent_address") or ""
    match_shield = got_shield == exp_shield
    match_transparent = got_transparent == exp_transparent

    print(f"verify-agent : {agent_name}")
    print(f"shield       : {got_shield}")
    print(f"expected     : {exp_shield}   {'✓' if match_shield else '✗ MISMATCH'}")
    print(f"transparent  : {got_transparent}")
    print(f"expected     : {exp_transparent}   {'✓' if match_transparent else '✗ MISMATCH'}")
    if match_shield and match_transparent:
        print("RESULT: PASS — recovery matches the live wallet")
        return 0
    print("RESULT: FAIL — addresses differ; do NOT fund, investigate (typo'd word?)")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
