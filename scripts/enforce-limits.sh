#!/bin/sh
# enforce-limits.sh — spend control wrapper around `pivx-agent-kit send`.
# Kit has no native limits; this wrapper enforces:
#   PER_TX_SAT    — max satoshis per transaction
#   DAILY_SAT     — max total satoshis per day (UTC)
#   FLOOR_SAT     — minimum balance kept (soft floor; denied below)
# Denied sends are journaled to the SQLite ledger + Telegram alert.
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

# amount in PIV -> sat
AMOUNT_SAT=$(python3 -c "print(int(float('$AMOUNT_PIV') * 1e8))")
NOW=$(date +%s)

# Balance (transparent + shield). Sync progress goes to stderr; JSON to stdout.
BAL_JSON=$(PIVX_AGENT="$AGENT" pivx-agent-kit balance 2>/dev/null)
BAL_SAT=$(python3 - "$BAL_JSON" <<'PYEOF'
import json, sys
b = json.loads(sys.argv[1])
pub = b.get("public_balance") or 0
priv = b.get("private_balance") or 0
print(int(float(pub) * 1e8 + float(priv) * 1e8))
PYEOF
)

# Today's spend
TODAY_SPENT=$(python3 - "$LEDGER_DB" "$NOW" <<'PYEOF'
import sqlite3, sys
db, now = sys.argv[1], int(sys.argv[2])
conn = sqlite3.connect(db)
try:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_sat),0) FROM spend_events WHERE direction='out' AND allowed=1 AND ts >= ?",
        (now - 86400,)).fetchone()
    print(row[0])
except Exception:
    print(0)
PYEOF
)

DENY=""
[ "$AMOUNT_SAT" -le "$PER_TX_SAT" ] || DENY="per-tx cap exceeded (max ${PER_TX_SAT} sat)"
[ "$((TODAY_SPENT + AMOUNT_SAT))" -le "$DAILY_SAT" ] || DENY="daily cap exceeded (${TODAY_SPENT}+${AMOUNT_SAT} > ${DAILY_SAT} sat)"
[ "$((BAL_SAT - AMOUNT_SAT))" -ge "$FLOOR_SAT" ] || DENY="balance floor would breach (${BAL_SAT} - ${AMOUNT_SAT} < ${FLOOR_SAT} sat)"

# Journal
python3 - "$LEDGER_DB" "$AGENT" "$NOW" "$AMOUNT_SAT" "${DENY:-allowed}" <<'PYEOF'
import sqlite3, sys
db, agent, now, sat, outcome = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]
conn = sqlite3.connect(db)
conn.execute("CREATE TABLE IF NOT EXISTS spend_events (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, ts INTEGER, direction TEXT, amount_sat INTEGER, txid TEXT, allowed INTEGER, reason TEXT)")
conn.execute("INSERT INTO spend_events (agent,ts,direction,amount_sat,allowed,reason) VALUES (?,?,?,?,?,?)",
             (agent, now, "out", sat, 0 if outcome != "allowed" else 1, outcome))
conn.commit()
PYEOF

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
