#!/bin/sh
# task-runner.sh — unattended PIVX Tasks bounty worker loop (M1).
# Lists eligible open tasks, ALERTS Kon on Telegram BEFORE signup (human-in-the-loop
# gate for the first N tasks; then fully unattended), introspects the task, dispatches
# work via scripts/work-dispatcher.py (templates + signed proof), submits with the
# deliverable attached, and journals every transition to the SQLite ledger.
#
# Improvements list integration:
#   item 1  task introspection — fresh `task get` after signup → $AGENT_DIR/task-<tid>.json,
#           journaled (title/category/verification) via ledger.py introspect-task-file
#   item 3  submit attaches the deliverable + proof.json (container paths)
#   item 8  pre-signup capability guard via work-dispatcher.py --check
#   item 10 retry+backoff kit wrapper, per-call timeout, 409 idempotency, TG on failure
#
# Ledger access goes through the committed helper scripts/ledger.py — no heredocs.
#
# Usage:
#   ./task-runner.sh <agent> [--dry-run] [--max-tasks N]
# Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (alerts), GATE_TASKS (default 3)
# Categories we can do unattended: dev, social, research, content.
# EXCLUDED: design, creative. Adjust ELIGIBLE_CATEGORIES below.

set -e
AGENT="${1:?usage: task-runner.sh <agent> [--dry-run]}"
DRY_RUN=0
MAX_TASKS=1
[ "$2" = "--dry-run" ] && DRY_RUN=1
[ -n "$3" ] && [ "$3" = "--max-tasks" ] && MAX_TASKS="$4"

GATE_TASKS="${GATE_TASKS:-3}"
ELIGIBLE_CATEGORIES='dev|social|research|content'
LEDGER_DB="${LEDGER_DB:-$HOME/.local/share/pivx-agent-kit/ledger.db}"
AGENT_DIR="$HOME/.local/share/pivx-agent-kit/$AGENT"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DISPATCHER="$SCRIPT_DIR/work-dispatcher.py"
MATRIX="$SCRIPT_DIR/../config/agent-capabilities.json"
mkdir -p "$AGENT_DIR/deliverables" "$AGENT_DIR/proofs"

# Gate metric: only rows with REAL signup progress count. 'applied' and
# 'pending-approval' rows are pre-inserted before anything real happens and
# must NOT open the gate (bug list #6).
SIGNUPS_DONE=$(python3 "$SCRIPT_DIR/ledger.py" count-signed-up "$LEDGER_DB" "$AGENT")

tg() { # tg <text>
    [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ] && \
        curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d chat_id="$TELEGRAM_CHAT_ID" -d text="$1" >/dev/null
}

journal() { # journal <task_id> <status> <reason>
    python3 "$SCRIPT_DIR/ledger.py" journal-task "$LEDGER_DB" "$AGENT" "$1" "$2" "${3:-}" "$(date +%s)"
}

# kit <label> <args...> — retry with exponential backoff (item 10).
# Output lands in /tmp/kit_$$_<label>.out for callers that need it.
kit() {
    label="$1"; shift
    tries=0; delay=1
    while [ "$tries" -lt 4 ]; do
        if timeout 120 env PIVX_AGENT="$AGENT" pivx-agent-kit "$@" > "/tmp/kit_$$_${label}.out" 2>&1; then
            return 0
        fi
        tries=$((tries + 1))
        sleep "$delay"
        delay=$((delay * 2))
    done
    tg "[PIVX task-runner] KIT FAILURE ($label) after 4 tries — $AGENT"
    return 1
}

echo "[task-runner] agent=$AGENT dry_run=$DRY_RUN signups_done=$SIGNUPS_DONE"

# 1. List open tasks (with retry)
kit list-task task list --status open --limit 50 || { echo "task list failed"; exit 1; }
LIST="/tmp/kit_$$_list-task.out"

# 2. Filter eligible (python parse; kit JSON has raw control chars → strict=False).
python3 "$SCRIPT_DIR/task_filter.py" "$LIST" "$ELIGIBLE_CATEGORIES" > /tmp/task_runner_filtered.json
COUNT=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" /tmp/task_runner_filtered.json)
echo "eligible tasks: $COUNT"
[ "$COUNT" -eq 0 ] && { echo "no eligible tasks; done"; exit 0; }

# 3. Pick first MAX_TASKS; task_filter.py pick dumps each task's full JSON to a
#    temp dir (used by the pre-signup capability guard) and prints picks lines.
PICKS="/tmp/task_runner_picks_$$.txt"
TASKS_DIR="/tmp/task_runner_tasks_$$"
SEP="$(printf '\t')"
python3 "$SCRIPT_DIR/task_filter.py" pick /tmp/task_runner_filtered.json "$MAX_TASKS" "$TASKS_DIR" > "$PICKS"

while IFS="$SEP" read -r TID TITLE AMOUNT; do
    [ -z "$TID" ] && continue
    TASK_JSON="$TASKS_DIR/task_${TID}.json"
    echo "--- task $TID: $TITLE ($AMOUNT PIV) ---"

    # 3b. Capability guard (item 8): skip tasks outside our templates BEFORE
    #     bothering Kon or burning a signup.
    if ! python3 "$DISPATCHER" --check "$TASK_JSON" --matrix "$MATRIX" > "/tmp/guard_$$_${TID}.out" 2>&1; then
        REASON=$(head -c 200 "/tmp/guard_$$_${TID}.out")
        echo "capability guard: skipping $TID — $REASON"
        journal "$TID" "skipped-capability" "$REASON"
        continue
    fi

    # Human-in-the-loop gate for the first N signups
    if [ "$SIGNUPS_DONE" -lt "$GATE_TASKS" ] && [ "$DRY_RUN" -eq 0 ]; then
        tg "[PIVX task-runner] $AGENT wants to sign up for task $TID: $TITLE ($AMOUNT PIV). Gate active (${SIGNUPS_DONE}/${GATE_TASKS}). Reply APPROVE to allow."
        journal "$TID" "pending-approval" "gate"
        echo "gate: awaiting Kon approval (signup NOT sent)"
        continue
    fi

    journal "$TID" "applied" ""

    if [ "$DRY_RUN" -eq 1 ]; then
        TMPL=$(python3 "$DISPATCHER" --route "$TASK_JSON")
        echo "dry-run: would signup + introspect + dispatch($TMPL) + submit deliverables/deliverable-$TID.txt"
        continue
    fi

    # 4. Signup (409/duplicate = idempotent success)
    signup_out="/tmp/kit_$$_signup_${TID}.out"
    if timeout 120 env PIVX_AGENT="$AGENT" pivx-agent-kit task signup "$TID" > "$signup_out" 2>&1; then
        journal "$TID" "signed-up" ""
        tg "[PIVX task-runner] $AGENT signed up: $TID — $TITLE"
    elif grep -qi 'already\|409\|duplicate' "$signup_out"; then
        journal "$TID" "signed-up" "already-signed-up (idempotent)"
    else
        journal "$TID" "signup-failed" "CLI error"
        tg "[PIVX task-runner] SIGNUP FAILED $TID: $TITLE"
        continue
    fi

    # 5. Introspection (item 1): fresh `task get` → agent dir; journal fields.
    if timeout 120 env PIVX_AGENT="$AGENT" pivx-agent-kit task get "$TID" > "$AGENT_DIR/task-$TID.json" 2>&1; then
        python3 "$SCRIPT_DIR/ledger.py" introspect-task-file "$LEDGER_DB" "$AGENT" "$AGENT_DIR/task-$TID.json"
        TASK_JSON="$AGENT_DIR/task-$TID.json"   # authoritative copy for dispatch
    else
        journal "$TID" "introspect-failed" "task get error; using list snapshot"
    fi

    # 6. WORK via dispatcher (item 2): templates write deliverables/ + proofs/,
    #    produce-proof.py signs and journals proof metadata (items 5+6).
    DISPATCH_OUT="/tmp/dispatch_$$_${TID}.out"
    if timeout 300 env PIVX_AGENT="$AGENT" python3 "$DISPATCHER" "$TASK_JSON" \
        --agent-dir "$AGENT_DIR" --matrix "$MATRIX" --ledger "$LEDGER_DB" > "$DISPATCH_OUT" 2>&1; then
        TMPL=$(grep '^template=' "$DISPATCH_OUT" | cut -d= -f2-)
        DELIVERABLE=$(grep '^deliverable=' "$DISPATCH_OUT" | cut -d= -f2-)
        PROOF=$(grep '^proof=' "$DISPATCH_OUT" | cut -d= -f2-)
        echo "work done: template=$TMPL deliverable=$DELIVERABLE proof=$PROOF"
        if [ -z "$DELIVERABLE" ]; then
            journal "$TID" "work-failed" "dispatcher produced no deliverable"
            tg "[PIVX task-runner] WORK FAILED $TID (no deliverable)"
            continue
        fi
    else
        RC=$?
        if [ "$RC" -eq 3 ]; then
            journal "$TID" "skipped-capability" "post-signup guard"
            tg "[PIVX task-runner] post-signup guard SKIPPED $TID"
            continue
        fi
        journal "$TID" "work-failed" "dispatcher rc=$RC"
        tg "[PIVX task-runner] WORK FAILED $TID (rc=$RC)"
        continue
    fi

    # 7. Submit with proof attached (item 3): container paths per pivx-agent-kit
    #    convention (/data/pivx-agent-kit/...). Body references the attachment.
    D_PATH="/data/pivx-agent-kit/deliverables/deliverable-$TID.txt"
    P_PATH="/data/pivx-agent-kit/proofs/proof-$TID.json"
    BODY="Work submitted by $AGENT for task $TID: $TITLE. Attached: deliverables/deliverable-$TID.txt (sha256 + signed proof in proofs/proof-$TID.json)."
    submit_out="/tmp/kit_$$_submit_${TID}.out"
    if timeout 120 env PIVX_AGENT="$AGENT" pivx-agent-kit task submit "$TID" "$BODY" "$D_PATH" "$P_PATH" > "$submit_out" 2>&1; then
        journal "$TID" "submitted" ""
        tg "[PIVX task-runner] submitted $TID with proof (deliverable-$TID.txt)"
    elif grep -qi 'already\|409\|duplicate' "$submit_out"; then
        journal "$TID" "submitted" "already-submitted (idempotent)"
    else
        journal "$TID" "submit-failed" "CLI error"
        tg "[PIVX task-runner] SUBMIT FAILED $TID"
    fi
done < "$PICKS"

rm -f "$PICKS" /tmp/task_runner_filtered.json /tmp/guard_$$_*.out /tmp/dispatch_$$_*.out /tmp/kit_$$_*.out
rm -rf "$TASKS_DIR"
echo "[task-runner] done"
