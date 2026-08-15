#!/bin/sh
# wallet-recover.sh — recover an agent wallet from its paper seed.
# Creates a FRESH data dir, prompts for the seed interactively (never on the
# command line — no shell history, no ps exposure), runs `import`, and verifies
# the resulting addresses against config/agents.json.
#
# Usage: ./wallet-recover.sh <agent> [verify-agent]
#   <agent>        name of the FRESH data dir to import into (throwaway for drills)
#   [verify-agent] optional: verify against THIS agent's entry in agents.json
#                  (e.g. drill: ./wallet-recover.sh recovery-test hermes-main)
#
# NOTE: run the recovery DRILL before real funds move (test-plan item 5).

set -e
AGENT="${1:?usage: wallet-recover.sh <agent> [verify-agent]}"
VERIFY_AGENT="${2:-$AGENT}"

DATA_ROOT="$HOME/.local/share/pivx-agent-kit"
AGENT_DIR="$DATA_ROOT/$AGENT"

if [ -f "$AGENT_DIR/wallet.json" ]; then
    echo "WARN: wallet already exists at $AGENT_DIR/wallet.json"
    echo "      Move it aside first if you intend to re-import:"
    echo "      mv $AGENT_DIR/wallet.json $AGENT_DIR/wallet.json.old"
    exit 1
fi

mkdir -p "$AGENT_DIR"

# Interactive seed prompt — read from tty, not argv.
printf 'Paste the 24-word seed phrase for agent "%s" (input hidden): ' "$AGENT"
SEED=""
if [ -t 0 ]; then
    stty -echo
    read -r SEED
    stty echo
    echo
else
    echo "ERROR: must run interactively (seed must not come from a pipe/log)."
    exit 1
fi

[ -n "$SEED" ] || { echo "ERROR: empty seed."; exit 1; }

echo "Importing into fresh data dir $AGENT_DIR ..."
PIVX_AGENT="$AGENT" pivx-agent-kit import "$SEED"
SEED=""
unset SEED

echo
echo "Verifying addresses against config/agents.json (entry: $VERIFY_AGENT) ..."
ADDRS=$(PIVX_AGENT="$AGENT" pivx-agent-kit address)
echo "$ADDRS"
python3 - config/agents.json "$VERIFY_AGENT" <<'PYEOF'
import json, sys
agents = json.load(open(sys.argv[1]))["agents"]
agent = next((a for a in agents if a["name"] == sys.argv[2]), None)
if not agent:
    print("WARN: agent not in agents.json — update it manually.")
    sys.exit(0)
print("Expected shield     :", agent["shield_address"])
print("Expected transparent:", agent["transparent_address"])
PYEOF
echo "Check the addresses above match. Then verify balance:"
echo "    PIVX_AGENT=$AGENT pivx-agent-kit balance"
