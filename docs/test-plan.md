# Test Plan — PIVX Agent-to-Agent Payments

Maps every test to the project's success criteria. All tests run on **mainnet with dust
amounts** (merchant-kit has no testnet). Real funds only after the recovery drill.

## Prereq: wallet + seed backup (Kon, before any funding)
- [ ] `pivx-agent-kit export` → seed on paper, offline. Confirm in chat.
- [ ] Fund transparent `DEd1j7RYyu8RVxLbBV4swKS3abwYQsyVoi` with 5–10 PIV.
- [ ] `pivx-agent-kit balance` shows non-zero.

## T1 — Wallet foundation (M0)
- [ ] `pivx-agent-kit address` matches config/agents.json.
- [ ] wallet.json perms 0600, kon-owned (`ls -la ~/.local/share/pivx-agent-kit/hermes-main/`).
- [ ] Second CLI invocation returns same addresses (device-key stability).
- [ ] `scripts/wallet-backup.sh hermes-main` exits 0, prints paper-seed reminder.
- [ ] `sign-message "test"` returns base64; verify via public verifymessage (see §7).

## T2 — Marketplace proof (M1) — success criterion #1
- [ ] `scripts/task-runner.sh hermes-main --dry-run` lists eligible tasks, no side effects.
- [ ] Gate works: first signup alerts Kon on Telegram, does NOT sign up without approval.
- [ ] Live signup + submit on an eligible task (Kon approves).
- [ ] On approval: ledger row `task_rewards` status=paid with txid; txid resolves on
      `https://explorer.pivxla.bz/tx/<txid>`.
- [ ] Rejection path: submit rejected → reason logged, no auto-retry, Telegram alert.
- [ ] Node-unreachable path: stop network → exponential backoff → alert after 3 failures.

## T3 — Merchant prototype (M2) — success criteria #2, #3
- [ ] Container build: `docker build -f config/Dockerfile.merchant -t pivx-merchant-kit .`
- [ ] `/healthz` returns 200; SQLite file present in data volume.
- [ ] Config: `rpc.pivxla.bz` reachable (`curl` §7); daemon starts clean.
- [ ] Simulated second party: second wallet (`buyer-bot`) pays a dust invoice →
      webhook receiver log shows `invoice.confirmed`; ledger `orders` row written;
      Telegram alert received.
- [ ] Buyer-side verification: delivered `sign-message` signature passes PIVX Core
      `verifymessage` for the seller's transparent address.
- [ ] Duplicate webhook delivery (`X-Merchant-Delivery-Id` replay) → no duplicate
      ledger rows (idempotent).
- [ ] Invoice expiry: unpaid invoice → `invoice.expired` webhook → alert.

## T4 — Hardening (M3)
- [ ] `scripts/enforce-limits.sh` denies over-cap send; ledger `spend_events` row +
      Telegram alert; allows under-cap.
- [ ] Second agent wallet provisioned (agent-2); independent data dir; MCP entry works.
- [ ] Daily digest script sends balance/rewards/orders summary to Telegram.

## T5 — 7-day unattended soak (success criterion #4)
- [ ] Cron `*/30` runs task-runner + poller; Telegram shows success/failure alerts.
- [ ] Canary: grep all logs for seed phrase fragments / mnemonic words → zero hits.
- [ ] Ledger consistent (no NULL statuses, no orphan orders).

## T6 — Recovery drill (success criterion #5) — run BEFORE real funds
- [ ] Fresh data dir `wallet-recover.sh hermes-main` with paper seed.
- [ ] `address` reproduces shield + transparent from agents.json.
- [ ] `balance` reproduces pre-drill value.

## T7 — Explorer verification (cross-cuts T2/T3)
- [ ] Reward txid + payment txid resolve on explorer.pivxla.bz.
