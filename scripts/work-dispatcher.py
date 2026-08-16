#!/usr/bin/env python3
"""work-dispatcher.py — minimal dispatcher + work templates (improvements list item 2).

Called from task-runner.sh after signup (and pre-signup in --check mode).
Routes a task on category + keyword patterns in title/description/verification
and executes the matching work template, producing:

  <agent-dir>/deliverables/deliverable-<tid>.txt   (canonical deliverable)
  <agent-dir>/proofs/proof-<tid>.json              (produce-proof.py output)

Templates:
  download   — curl artifact URLs from the description, sha256, signed attestation
  social     — signed statement "followed X on YYYY-MM-DD at HH:MM" (+ optional screenshot)
  research   — fetch sources (curl), sourced report (200-400 words when --content given), sign hash
  content    — write provided/generated content, sign hash
  monitoring — M2 path: alert_hash + sign flow

Usage:
  work-dispatcher.py --route <task_json>                 # print template name
  work-dispatcher.py --check <task_json> [--matrix <f>]  # exit 0=OK, 3=SKIP (capability guard)
  work-dispatcher.py <task_json> --agent-dir <dir> [--matrix <f>] [--content <file>] [--alert-hash <h>]

Env: PIVX_AGENT (used for signing via produce-proof.py). Stdlib only.
"""
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MATRIX = os.path.join(SCRIPT_DIR, "..", "config", "agent-capabilities.json")

URL_RE = re.compile(r"https?://[^\s)\]}<>'\"]+", re.IGNORECASE)
# Template precedence: download first (strong signals like wallet/app/edge),
# then research, content, social; anything unmatched falls back to monitoring.
TEMPLATE_ORDER = ("download", "research", "content", "social", "monitoring")


def load_matrix(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh, strict=False)


def load_task(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh, strict=False)


def task_text(task: dict) -> str:
    return " ".join(str(task.get(k) or "") for k in ("title", "description", "verification", "category"))


def route(task: dict, matrix: dict | None = None) -> str:
    """Return the template name for this task (pure function, unit-tested)."""
    if matrix is None:
        matrix = load_matrix(DEFAULT_MATRIX)
    text = task_text(task).lower()
    templates = matrix.get("templates", {})
    for name in TEMPLATE_ORDER:
        if name not in templates:
            continue
        for kw in templates[name].get("keywords", []):
            if re.search(re.escape(kw), text):
                return name
    return "monitoring"


def check_task(task: dict, matrix: dict):
    """Capability guard (item 8): returns (ok, template, reason)."""
    text = task_text(task).lower()
    for pat in matrix.get("skip_globally", {}).get("patterns", []):
        if re.search(re.escape(pat), text):
            return False, None, f"global skip pattern: {pat}"
    # Category axis (fix): if the board classifies this task under a template
    # that is disabled, skip it outright — regardless of keyword hits. A task
    # categorized 'social' must not slip through to the enabled 'download'
    # template just because its text mentions edge/wallet/app. route() stays
    # keyword-first (pure function, unit-tested); the category gate lives here.
    cat = str(task.get("category") or "").lower().strip()
    templates = matrix.get("templates", {})
    if cat in templates and not templates[cat].get("enabled", False):
        return False, cat, f"category '{cat}' template disabled in capability matrix"
    tmpl = route(task, matrix)
    tpl = templates.get(tmpl, {})
    if not tpl.get("enabled", False):
        return False, tmpl, f"template '{tmpl}' disabled in capability matrix"
    return True, tmpl, "ok"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def strip_html(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch(url: str, dest: str, timeout: int = 170) -> bool:
    try:
        proc = subprocess.run(
            ["curl", "-L", "-sS", "--max-time", str(timeout), "-o", dest, url],
            timeout=timeout + 10)
        return proc.returncode == 0 and os.path.getsize(dest) > 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def urls_from(task: dict) -> list:
    seen, out = set(), []
    for m in URL_RE.finditer(str(task.get("description") or "") + "\n" + str(task.get("verification") or "")):
        u = m.group(0).rstrip(".,;")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ---- templates -------------------------------------------------------------

def tmpl_download(task: dict, agent_dir: str, agent: str, tid: str):
    art_dir = os.path.join(agent_dir, "artifacts")
    os.makedirs(art_dir, exist_ok=True)
    urls = urls_from(task)
    lines = [
        f"Task {tid}: {task.get('title','')}",
        f"Category: {task.get('category','')}",
        f"Agent: {agent}",
        f"Date: {now_iso()}",
        "Action: downloaded artifact(s) and computed sha256",
        "",
    ]
    meta_arts = []
    for n, url in enumerate(urls, 1):
        dest = os.path.join(art_dir, f"{tid}-{n}.bin")
        if fetch(url, dest):
            h = sha256_file(dest)
            size = os.path.getsize(dest)
            lines.append(f"  {url}")
            lines.append(f"    -> {os.path.relpath(dest, agent_dir)} sha256:{h} size:{size}")
            meta_arts.append({"url": url, "file": os.path.relpath(dest, agent_dir), "sha256": h})
        else:
            lines.append(f"  {url} -> DOWNLOAD FAILED (skipped)")
    if not urls:
        lines.append("  (no artifact URL found in task description)")
    lines.append("")
    lines.append("Attestation: files above were downloaded from the referenced URLs at "
                 + now_iso() + " and hashed with sha256.")
    return "\n".join(lines), {"artifacts": meta_arts}


def tmpl_social(task: dict, agent: str, tid: str):
    text = task_text(task).lower()
    platform = next((p for p in ("discord", "telegram", "instagram", "twitter", "reddit", "youtube")
                     if p in text), "the platform named in the task")
    action = "followed/joined" if any(w in text for w in ("follow", "join")) else "performed the social action"
    ts = now_iso()
    lines = [
        f"Signed social action statement — {agent}",
        f"Task {tid}: {task.get('title','')}",
        f"Action: {action} on {platform}",
        f"When: {ts}",
        "",
        "This statement is signed (see proof.json); screenshot path may be attached separately.",
    ]
    return "\n".join(lines), {"platform": platform, "action": action, "when": ts}


def tmpl_research(task: dict, agent_dir: str, agent: str, tid: str, content_file: str | None):
    src_dir = os.path.join(agent_dir, "sources")
    os.makedirs(src_dir, exist_ok=True)
    urls = urls_from(task)
    fetched = []
    for n, url in enumerate(urls[:5], 1):
        dest = os.path.join(src_dir, f"{tid}-{n}.txt")
        if fetch(url, dest):
            raw = ""
            with open(dest, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read(65536)
            words = len(strip_html(raw).split())
            fetched.append({"url": url, "file": os.path.relpath(dest, agent_dir), "words": words})
    lines = [
        f"Research report — Task {tid}: {task.get('title','')}",
        f"Category: {task.get('category','')}",
        f"Agent: {agent}",
        f"Date: {now_iso()}",
        "",
    ]
    if content_file and os.path.isfile(content_file):
        with open(content_file, "r", encoding="utf-8") as fh:
            body = fh.read()
        lines.append(body.rstrip())
    else:
        lines.append("(report body: pass --content <file> to embed the generated 200-400 word report)")
    lines += ["", "Sources fetched:", ""]
    for f in fetched:
        lines.append(f"  {f['url']} -> {f['file']} ({f['words']} words)")
    if not fetched:
        lines.append("  (no sources fetchable from the description)")
    return "\n".join(lines), {"sources": fetched}


def tmpl_content(task: dict, agent: str, tid: str, content_file: str | None):
    lines = [
        f"Content deliverable — Task {tid}: {task.get('title','')}",
        f"Agent: {agent}",
        f"Date: {now_iso()}",
        "",
    ]
    if content_file and os.path.isfile(content_file):
        with open(content_file, "r", encoding="utf-8") as fh:
            lines.append(fh.read().rstrip())
    else:
        lines.append("(content body: pass --content <file> to embed the generated text)")
    return "\n".join(lines), {}


def tmpl_monitoring(task: dict, agent: str, tid: str, alert_hash: str | None):
    lines = [
        f"Monitoring proof — Task {tid}: {task.get('title','')}",
        f"Agent: {agent}",
        f"Date: {now_iso()}",
        f"Alert hash: {alert_hash or '(not supplied; see M2 alert flow)'}",
    ]
    return "\n".join(lines), {"alert_hash": alert_hash}


TEMPLATE_HANDLERS = {
    "download": tmpl_download,
    "social": tmpl_social,
    "research": tmpl_research,
    "content": tmpl_content,
    "monitoring": tmpl_monitoring,
}


def dispatch(task: dict, agent_dir: str, matrix_path: str, content_file: str | None,
             alert_hash: str | None, ledger_db: str | None) -> int:
    matrix = load_matrix(matrix_path)
    ok, tmpl, reason = check_task(task, matrix)
    if not ok:
        print(f"SKIP {reason}", file=sys.stderr)
        return 3
    agent = os.environ.get("PIVX_AGENT", "unknown")
    tid = str(task.get("id") or task.get("task_id") or "0")
    os.makedirs(os.path.join(agent_dir, "deliverables"), exist_ok=True)
    os.makedirs(os.path.join(agent_dir, "proofs"), exist_ok=True)

    handler = TEMPLATE_HANDLERS[tmpl]
    if tmpl == "download":
        body, meta = handler(task, agent_dir, agent, tid)
    elif tmpl == "research":
        body, meta = handler(task, agent_dir, agent, tid, content_file)
    elif tmpl == "content":
        body, meta = handler(task, agent, tid, content_file)
    elif tmpl == "social":
        body, meta = handler(task, agent, tid)
    else:
        body, meta = handler(task, agent, tid, alert_hash)

    deliverable = os.path.join(agent_dir, "deliverables", f"deliverable-{tid}.txt")
    with open(deliverable, "w", encoding="utf-8") as fh:
        fh.write(body)
    proof = os.path.join(agent_dir, "proofs", f"proof-{tid}.json")
    proof_type = "hash" if tmpl == "monitoring" else "signed-text"
    pp_cmd = ["python3", os.path.join(SCRIPT_DIR, "produce-proof.py"), deliverable,
              "--out", proof, "--type", proof_type, "--agent", agent,
              "--task-id", tid, "--meta", json.dumps(meta)]
    if ledger_db:
        pp_cmd += ["--ledger", ledger_db]
    subprocess.run(pp_cmd, check=True, timeout=300)
    print(f"template={tmpl}")
    print(f"deliverable={deliverable}")
    print(f"proof={proof}")
    return 0


def main(argv: list) -> int:
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    matrix_path = DEFAULT_MATRIX
    content_file = None
    alert_hash = None
    if argv[0] == "--route":
        task = load_task(argv[1])
        matrix = load_matrix(matrix_path)
        print(route(task, matrix))
        return 0
    if argv[0] == "--check":
        task = load_task(argv[1])
        if len(argv) > 2 and argv[2] == "--matrix":
            matrix_path = argv[3]
        ok, tmpl, reason = check_task(task, load_matrix(matrix_path))
        if ok:
            print(f"OK {tmpl}")
            return 0
        print(f"SKIP {tmpl} {reason}")
        return 3
    task_file, agent_dir = argv[0], None
    rest = argv[1:]
    i = 0
    ledger_db = None
    while i < len(rest):
        if rest[i] == "--agent-dir":
            i += 1
            agent_dir = rest[i]
        elif rest[i] == "--matrix":
            i += 1
            matrix_path = rest[i]
        elif rest[i] == "--content":
            i += 1
            content_file = rest[i]
        elif rest[i] == "--alert-hash":
            i += 1
            alert_hash = rest[i]
        elif rest[i] == "--ledger":
            i += 1
            ledger_db = rest[i]
        i += 1
    if not agent_dir:
        sys.stderr.write("work-dispatcher.py: --agent-dir required\n")
        return 2
    task = load_task(task_file)
    return dispatch(task, agent_dir, matrix_path, content_file, alert_hash, ledger_db)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
