#!/bin/sh
# enforce-limits.sh — spend control wrapper around `pivx-agent-kit send`.
# Kit has no native limits; this wrapper enforces:
#   PER_TX_SAT    — max satoshis per transaction
#   DAILY_SAT     — max total satoshis per day (UTC)
#   FLOOR_SAT     — minimum balance kept (soft floor; denied below)
# Denied sends are journaled to the SQLite ledger + Telegram alert.
#
# Amounts are converted with Decimal (scripts/pivutil.py) — float math lost
# satoshis on large amounts (bug list #8). Ledger access via scripts/ledger.py.
#
# Usage: enforce-limits.sh <to_address> <amount_piv> [--from public|private] [memo]
#   Overrides via env: PER_TX_SAT DAILY_SAT FLOOR_SAT (defaults below).

set -e
TO_ADDR="${1:?usage: enforce-limits.sh <to> <amount_piv> [--from public|private]}"
AMOUNT_PIV="${2:?amount required}"
shift 2

PER_TX_SAT="${PER_TX_SAT:-50000000}"    # 0.5 PIV default per-tx cap
DAILY_SAT="${DAILY_SAT:-100000000}"     # 1 PIV/day default
FLOOR_SAT="${FLOOR_SAT:-10000000}"      # keep 0.1 PIV floor
AGENT="${PIVX_AGENT:-hermes-main}"
LEDGER_DB="${LEDGER_DB:-$HOME/.local/share/pivx-agent-kit/ledger.db}"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# amount in PIV -> sat (exact Decimal conversion)
AMOUNT_SAT=$(python3 "$SCRIPT_DIR/pivutil.py" piv-to-sat "$AMOUNT_PIV")
NOW=$(date +%s)

# Balance (transparent + shield) — exact Decimal sum of public+private.
# Sync progress goes to stderr; JSON to stdout.
BAL_JSON=$(PIVX_AGENT="$AGENT" pivx-agent-kit balance 2>/dev/null)
BAL_SAT=$(printf '%s' "$BAL_JSON" | python3 "$SCRIPT_DIR/pivutil.py" balance-to-sat)

# Today's spend (UTC, last 24 h)
TODAY_SPENT=$(python3 "$SCRIPT_DIR/ledger.py" spent-today "$LEDGER_DB" "$NOW")

DENY=""
[ "$AMOUNT_SAT" -le "$PER_TX_SAT" ] || DENY="per-tx cap exceeded (max ${PER_TX_SAT} sat)"
[ "$((TODAY_SPENT + AMOUNT_SAT))" -le "$DAILY_SAT" ] || DENY="daily cap exceeded (${TODAY_SPENT}+${AMOUNT_SAT} > ${DAILY_SAT} sat)"
[ "$((BAL_SAT - AMOUNT_SAT))" -ge "$FLOOR_SAT" ] || DENY="balance floor would breach (${BAL_SAT} - ${AMOUNT_SAT} < ${FLOOR_SAT} sat)"

# Journal every attempt (allowed or denied)
python3 "$SCRIPT_DIR/ledger.py" journal-spend "$LEDGER_DB" "$AGENT" "$NOW" "$AMOUNT_SAT" "${DENY:-allowed}"

if [ -n "$DENY" ]; then
    echo "DENIED: $DENY"
    [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ] && \
        curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d chat_id="$TELEGRAM_CHAT_ID" \
        -d text="[PIVX] spend DENIED $AGENT: $AMOUNT_PIV PIV → $TO_ADDR ($DENY)" >/dev/null
    exit 1
fi

echo "OK: sending $AMOUNT_PIV PIV → $TO_ADDR (balance ${BAL_SAT} sat, today ${TODAY_SPENT} sat)"
PIVX_AGENT="$AGENT" pivx-agent-kit send "$TO_ADDR" "$AMOUNT_PIV" "$@"
