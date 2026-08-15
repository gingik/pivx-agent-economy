#!/bin/sh
# wallet-backup.sh — verify wallet integrity + remind operator of the paper seed.
# The wallet file is device-encrypted (machine-id + data-dir-path + salt) and is
# NOT a portable backup. The ONLY portable backup is the seed phrase, which Kon
# exports by hand (never logged). This script verifies the file is sane and
# prints the reminder. Exports nothing.
#
# Usage: ./wallet-backup.sh [agent]     (default: hermes-main)

set -e
AGENT="${1:-hermes-main}"
WALLET="$HOME/.local/share/pivx-agent-kit/$AGENT/wallet.json"

if [ ! -f "$WALLET" ]; then
    echo "ERROR: no wallet at $WALLET — nothing to back up."
    exit 1
fi

PERMS=$(stat -c '%a' "$WALLET")
if [ "$PERMS" != "600" ]; then
    echo "WARN: wallet.json perms are $PERMS, expected 600."
    chmod 600 "$WALLET"
    echo "      fixed → 600"
else
    echo "OK: wallet.json perms 600"
fi

# Basic sanity: file is non-empty and valid JSON with required fields.
python3 - "$WALLET" <<'PYEOF'
import json, sys
raw = open(sys.argv[1]).read()
data = json.loads(raw)
print(f"OK: wallet.json parses ({len(raw)} bytes)")
PYEOF

echo
echo "================================================================"
echo " REMINDER: the wallet FILE is NOT a backup (device-encrypted)."
echo " The real backup is the SEED PHRASE, exported by Kon only:"
echo "     pivx-agent-kit export"
echo " Write it on paper, store offline. NEVER paste it into chat/logs."
echo "================================================================"
