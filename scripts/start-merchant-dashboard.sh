#!/bin/bash
# Start the PIVX merchant dashboard (idempotent, mirrors coldcard pattern).
cd /home/kon/github/pivx-agent-economy || exit 1
if pgrep -f "merchant-dashboard.py" > /dev/null; then
    echo "already running (pid $(pgrep -f 'merchant-dashboard.py'))"
    exit 0
fi
nohup ./venv/bin/python scripts/merchant-dashboard.py --port 5030 >> scripts/dashboard.log 2>&1 &
echo "started pid $!"
