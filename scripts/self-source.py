#!/usr/bin/env python3
"""self-source.py — M3: turn the agent from pure worker into a marketplace participant.

Creates tasks the agent can fulfill itself (e.g. "produce a 300-word research
summary on topic X for 0.5 PIV") and monitors the board for self-created
bounties that have been picked up.

Safety: task creation is DRY-RUN unless --create is passed. Creating a task is
a real on-chain-adjacent board action (posting a bounty); the dry-run default
prevents accidental spends/commitments.

Usage:
  self-source.py <agent> --title T --description D --category C --amount A
                 [--verification V] [--currency PIV] [--quantity Q] [--min-rep R]
                 [--create] [--db <ledger.db>] [--no-tg]
  self-source.py <agent> --monitor [--db <ledger.db>] [--no-tg]

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (alerts on create/monitor hits).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER_DB = os.path.expanduser("~/.local/share/pivx-agent-kit/ledger.db")
AGENTS_ROOT = os.path.expanduser("~/.local/share/pivx-agent-kit")


def run_kit(agent: str, args: list, timeout: int = 120) -> dict:
    out = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False).name
    env = dict(os.environ, PIVX_AGENT=agent)
    subprocess.run(["timeout", str(timeout), "pivx-agent-kit", *args],
                   env=env, stdout=open(out, "w"), stderr=subprocess.STDOUT,
                   check=False, timeout=timeout + 10)
    try:
        with open(out, "r", encoding="utf-8") as fh:
            return json.load(fh, strict=False)
    except Exception:
        return {}
    finally:
        os.unlink(out)


def agent_handle(agent: str) -> str:
    try:
        with open(os.path.join(AGENTS_ROOT, agent, "tasks_state.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("handle", "")
    except Exception:
        return ""


def journal(agent: str, task_id: str, status: str, reason: str, db: str) -> None:
    subprocess.run(
        ["python3", os.path.join(SCRIPT_DIR, "ledger.py"), "journal-task",
         db, agent, str(task_id), status, reason or "", str(int(time.time()))],
        check=False)


def tg(text: str) -> None:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        import urllib.request
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            data=f"chat_id={chat}&text={text}".encode(), timeout=30)
    except Exception:
        pass


def cmd_create(args) -> int:
    flags = ["task", "create",
             "--title", args.title, "--description", args.description,
             "--category", args.category, "--amount", str(args.amount)]
    if args.verification:
        flags += ["--verification", args.verification]
    if args.currency:
        flags += ["--currency", args.currency]
    if args.quantity:
        flags += ["--quantity", str(args.quantity)]
    if args.min_rep is not None:
        flags += ["--min-rep", str(args.min_rep)]

    print("[self-source] would run: pivx-agent-kit " + " ".join(flags))
    if not args.create:
        print("[self-source] DRY-RUN (pass --create to actually post the task)")
        return 0

    resp = run_kit(args.agent, flags)
    tid = resp.get("id", resp.get("task_id", ""))
    if not tid:
        print(f"[self-source] create failed: {json.dumps(resp)[:300]}")
        return 1
    print(f"[self-source] created task {tid}: {args.title} ({args.amount} {args.currency or 'PIV'})")
    journal(args.agent, tid, "self-created",
            f"{args.category}: {args.title[:120]}", args.db)
    if not args.no_tg:
        tg(f"[PIVX self-source] posted task {tid}: {args.title} ({args.amount} {args.currency or 'PIV'})")
    return 0


def cmd_monitor(args) -> int:
    handle = agent_handle(args.agent)
    if not handle:
        print("[self-source] cannot read agent handle from tasks_state.json")
        return 1
    data = run_kit(args.agent, ["task", "list", "--status", "open", "--limit", "50"])
    items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    mine = [t for t in items if str(t.get("creator_handle", "")) == handle]
    if not mine:
        print(f"[self-source] no open tasks created by {handle}")
        return 0
    for t in mine:
        line = f"task {t.get('id')}: {t.get('title')} ({t.get('quoted_amount', t.get('bounty_sat', ''))} PIV)"
        print(f"[self-source] open self-created: {line}")
    if not args.no_tg:
        tg(f"[PIVX self-source] {len(mine)} open self-created bounty(s) — "
           f"{', '.join(str(t.get('id')) for t in mine)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent", help="agent dir name, e.g. hermes-main")
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--category")
    ap.add_argument("--amount", type=float)
    ap.add_argument("--verification")
    ap.add_argument("--currency", default="PIV")
    ap.add_argument("--quantity", type=int)
    ap.add_argument("--min-rep", type=int)
    ap.add_argument("--create", action="store_true", help="actually post (default: dry-run)")
    ap.add_argument("--monitor", action="store_true", help="list open self-created bounties")
    ap.add_argument("--db", default=LEDGER_DB)
    ap.add_argument("--no-tg", action="store_true")
    args = ap.parse_args()

    if args.monitor:
        return cmd_monitor(args)
    if not (args.title and args.description and args.category and args.amount is not None):
        ap.error("--title, --description, --category and --amount are required "
                 "(or use --monitor)")
    return cmd_create(args)


if __name__ == "__main__":
    sys.exit(main())
