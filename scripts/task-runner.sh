#!/bin/sh
# task-runner.sh — unattended PIVX Tasks bounty worker loop (M1).
# Lists eligible open tasks, ALERTS Kon on Telegram BEFORE signup (human-in-the-loop
# gate for the first N tasks; then fully unattended), submits work, and journals
# every transition to the SQLite ledger (task_rewards).
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
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

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

echo "[task-runner] agent=$AGENT dry_run=$DRY_RUN signups_done=$SIGNUPS_DONE"

# 1. List open tasks
LIST=$(PIVX_AGENT="$AGENT" pivx-agent-kit task list --status open --limit 50 2>&1)
echo "$LIST" > /tmp/task_runner_list.json

# 2. Filter eligible (python parse; kit JSON has raw control chars → strict=False).
#    Uses the committed helper scripts/task_filter.py (same dir as this script).
FILTERED=$(python3 "$SCRIPT_DIR/task_filter.py" /tmp/task_runner_list.json "$ELIGIBLE_CATEGORIES" 2>/dev/null)

COUNT=$(printf '%s' "$FILTERED" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
echo "eligible tasks: $COUNT"
[ "$COUNT" -eq 0 ] && { echo "no eligible tasks; done"; exit 0; }

# 3. Pick first MAX_TASKS into a temp file, then iterate with a file-redirected
#    loop — the old `... | while read` ran in a SUBSHELL and journal/counter
#    state was lost (bug list #7).
PICKS="/tmp/task_runner_picks_$$.txt"
SEP="$(printf '\t')"
printf '%s' "$FILTERED" | python3 -c "import json,sys; [print(t['id'] + '$SEP' + t.get('title','')[:80] + '$SEP' + str(t.get('amount',''))) for t in json.load(sys.stdin)[:$MAX_TASKS]]" > "$PICKS"

while IFS="$SEP" read -r TID TITLE AMOUNT; do
    [ -z "$TID" ] && continue
    echo "--- task $TID: $TITLE ($AMOUNT PIV) ---"

    # Human-in-the-loop gate for the first N signups
    if [ "$SIGNUPS_DONE" -lt "$GATE_TASKS" ] && [ "$DRY_RUN" -eq 0 ]; then
        tg "[PIVX task-runner] $AGENT wants to sign up for task $TID: $TITLE ($AMOUNT PIV). Gate active (${SIGNUPS_DONE}/${GATE_TASKS}). Reply APPROVE to allow."
        journal "$TID" "pending-approval" "gate"
        echo "gate: awaiting Kon approval (signup NOT sent)"
        continue
    fi

    journal "$TID" "applied" ""

    if [ "$DRY_RUN" -eq 1 ]; then
        echo "dry-run: would signup + work + submit $TID"
        continue
    fi

    # 4. Signup
    if PIVX_AGENT="$AGENT" pivx-agent-kit task signup "$TID" 2>&1; then
        journal "$TID" "signed-up" ""
        tg "[PIVX task-runner] $AGENT signed up: $TID — $TITLE"
    else
        journal "$TID" "signup-failed" "CLI error"
        tg "[PIVX task-runner] SIGNUP FAILED $TID: $TITLE"
        continue
    fi

    # 5. WORK: placeholder — real agents run their own work function.
    # TODO(M1): agent-specific work generation for the task description.
    echo "performing work for $TID ..."

    # 6. Submit (approval requires rep ≥ min_worker_rep; new wallets start at 0)
    if PIVX_AGENT="$AGENT" pivx-agent-kit task submit "$TID" "Work submitted by $AGENT (see attachments)" 2>&1; then
        journal "$TID" "submitted" ""
        tg "[PIVX task-runner] submitted $TID"
    else
        journal "$TID" "submit-failed" "CLI error"
        tg "[PIVX task-runner] SUBMIT FAILED $TID"
    fi
done < "$PICKS"
rm -f "$PICKS"

echo "[task-runner] done"
