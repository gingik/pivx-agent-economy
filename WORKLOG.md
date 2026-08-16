# Work Log — PIVX Tasks Bounty #18 (Edge Wallet, 2.0 PIV)

**Repo:** pivx-agent-economy (this repository)
**Date of work:** 2026-08-15
**Status:** ⚠️ Work done, deliverable produced — **submission never completed, reward unclaimed**

---

## 1. The job

| Field | Value |
|---|---|
| Task ID | **18** |
| Title | Download Edge Wallet (`Descarga Edge Wallet` — Spanish listing) |
| Creator | ONeZetty (`azure-crane-037`) |
| Reward | **2.0 PIV** (200,000,000 sat) |
| Verification required | Screenshot of Edge Wallet installed on a mobile device, showing a PIVX wallet |
| Link | https://dl.edge.app/onezetty |

## 2. Timeline (from our own logs)

| Timestamp (UTC) | Event | Evidence |
|---|---|---|
| 2026-08-15 13:34 | Agent **applied** to task #18 | `task_rewards` ledger: `(1, '18', 'hermes-main', NULL, 'applied', NULL, '', 1786791240)` |
| 2026-08-15 19:20 | **Deliverable produced** | `~/.local/share/pivx-agent-kit/hermes-main/edge-wallet-screenshot.jpg` (46,488 bytes) |
| — | **Submission step — NOT completed** | Ledger has no `submitted` transition; `task notifications --unread` = 0 items; board shows no worker attached to us (`worker_handle: null`) |
| 2026-08-16 16:15 | Wallet check | `4.98997720 PIV` — exactly the 5.0 PIV funding float minus the 0.0100228 PIV test spend. **No incoming payment.** |

**Agent identity:** handle `sharp-elk-087`, transparent address `DEd1j7RYyu8RVxLbBV4swKS3abwYQsyVoi` (also the payout address on file).

## 3. Conclusion — why no payment was received

The 2.0 PIV was **not withheld — it was never claimed**.
The board-side status for task #18 shows our slot was never submitted
(`slots: completed 6, submitted 1, rejected 5, abandoned 3, available 3, in_flight 1, total 10`;
our handle appears nowhere). The local ledger confirms the application was
recorded but the `task submit` step never fired. Without a submission there is
nothing for the task creator to approve, so no payout was triggered.

## 4. Work performed for this build (full git history, 2026-08-15)

```
f97059e 21:43 feat: merchant status dashboard (Flask :5030, basic auth, @reboot)
59aebb1 21:27 fix: backfill mined height for mempool-matched payments
d6fd78e 20:12 fix: gate shield sync for transparent-only deployments
0ebe776 19:51 feat: webhook receiver launcher (BIND_ADDR env), deploy docs
1976e7c 19:43 docs: merchant deploy section — env-file run pattern
b69f1a8 19:40 patch: fix unlock passphrase stdin detection for docker
f6dd46a 19:05 Fix wallet-recover.sh dash compatibility
a98c0db 17:56 Fix bug list: webhook txid/idempotency/signing/injection; heredoc->helpers; Decimal; canary scanner
7f0dfcf 17:26 wallet-recover.sh: support verify-agent for recovery drills
8aabd55 17:21 Remove pycache from tracking
4a08cdc 12:56 Add .gitignore (pycache, .env)
220ff92 12:55 M0: PIVX agent economy scaffold — wallet, MCP, task-runner, merchant, ledger, docs
```

**What the build delivered (beyond the screenshot):**
- Per-agent PIVX wallet provisioning via `pivx-agent-kit` (agent `hermes-main`), MCP stdio integration.
- `pivx-merchant-kit` deployed in Docker (Ubuntu 24.04) — invoice-per-address, confirmation state machine, HMAC webhooks, SQLite ledger.
- **3 upstream bug patches** (vendor `pivx-merchant-kit`): unlock passphrase env fallback, shield-sync gate, mempool-height backfill — the last verified live.
- End-to-end payment test **confirmed on mainnet**: 1.0 PIV paid to invoice `hermes-test-002`, txid `bb8bfeaa3ee231ec52a233fafb49b3c9b57f40334474303cd5d4f577da06bc67`, 25 confirmations, webhook delivered HTTP 200, Telegram alert sent.
- Live merchant dashboard: http://192.168.0.41:5030/ (daemon health, wallet balance, invoices, payments, webhook ledger).

## 5. How to verify every claim

```bash
# 1. Work log (this file's source of truth)
cd ~/github/pivx-agent-economy && git log --oneline

# 2. Wallet balance — shows no payout
pivx-agent-kit balance

# 3. Task board status — our slot never submitted
pivx-agent-kit task get 18

# 4. Local ledger — application recorded, no submission
python3 -c "import sqlite3; db=sqlite3.connect('file:/home/kon/.local/share/pivx-agent-kit/ledger.db?mode=ro', uri=True); print(db.execute('SELECT * FROM task_rewards').fetchall())"

# 5. Deliverable file
ls -la ~/.local/share/pivx-agent-kit/hermes-main/edge-wallet-screenshot.jpg
```

## 6. Next step

Submit the deliverable so the creator can approve and pay:

```bash
pivx-agent-kit task submit 18 "<short body>" ~/.local/share/pivx-agent-kit/hermes-main/edge-wallet-screenshot.jpg
```

**Caveat:** the screenshot must show Edge Wallet genuinely installed on a mobile
device with a PIVX wallet inside (per the verification rule). Review it visually
before submitting — a wrong screenshot risks a rejected slot.
