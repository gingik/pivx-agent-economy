# Security Checklist — PIVX Agent-to-Agent Payments

## Wallet & keys
- [ ] wallet.json perms 600, owned by kon (not root).
- [ ] Seed phrase: exported by Kon ONLY (`pivx-agent-kit export`), written to paper,
      stored offline. NEVER in chat, logs, shell history, or this repo.
- [ ] Wallet file is device-encrypted (machine-id + data-dir-path + salt) — NOT a
      backup. Only the paper seed recovers a wallet.
- [ ] Recovery drills done before real funds move.
- [ ] No seed material in any git commit (repo has no .env with keys; agents.json
      holds public addresses only — safe to commit).
- [ ] Spend limits enforced at wrapper level (kit has no native limits) — keep
      `enforce-limits.sh` in the send path, never bypass with direct `pivx-agent-kit send`.

## Wallet rotation
- [ ] Public exposure of the transparent address (repo docs, txids, dashboard) is
      watch-only — not a funds risk. Rotation restarts with a clean history.
- [ ] Rotate ONLY after testing is done AND the pending bounty payout has landed —
      the payout arrives on the CURRENT address (agent-kit profile is bound to it).
      Rotating early can strand the reward on a retired wallet.
- [ ] Procedure: (1) `scripts/wallet-backup.sh` — export + store the OLD seed
      offline (keep it until the payout confirms, as bounty proof);
      (2) generate a fresh wallet (fresh data dir + seed import per
      `scripts/wallet-recover.sh`); (3) update the address in
      `config/agents.json` and dashboard refs; (4) re-run
      `scripts/wallet-check.py` + `scripts/verify-addresses.py`.
- [ ] The old address remains valid for receiving (chain-side) — it is retired,
      not deleted; it just stops being used for new invoices.
- [ ] After rotation, never reuse the old seed for a new wallet (address
      derivation is deterministic — reuse re-exposes the old history).

## Secrets & logs
- [ ] All secrets in this repo appear only as `[REDACTED]` + key name + length.
- [ ] `.env` files (if created) are gitignored; never committed.
- [ ] No secrets in Telegram alerts, webhook receiver logs, or task submissions.
- [ ] Seed prompt in wallet-recover.sh is hidden (stty -echo) and refuses non-tty.
- [ ] Canary test in soak (T5): grep logs for mnemonic fragments — zero hits.

## Webhooks (merchant-kit)
- [ ] HMAC-SHA256 `X-Merchant-Signature` verified on every webhook POST.
- [ ] Replay protection via `X-Merchant-Delivery-Id` dedupe (idempotent ledger upserts).
- [ ] Webhook receiver bound to 127.0.0.1 only; front with TLS reverse proxy if remote.
- [ ] `auth_token` on merchant API is strong (≥32 hex chars) and per-deployment.
- [ ] Webhook secret and auth_token differ from each other.

## Data
- [ ] Ledger contains no PII beyond payer transparent addresses.
- [ ] SQLite WAL mode; backups: `sqlite3 ledger.db ".backup ledger.bak"` on schedule.
- [ ] Memo annotation known-unavailable on transparent channel (shield→shield only) —
      documented limitation, not a security gap.

## Network
- [ ] Tor SOCKS5 :9050 available for privacy-sensitive balance/task polling if needed.
- [ ] Public RPC/explorer endpoints verified reachable before deploy (curl §7).
- [ ] Merchant daemon binds 127.0.0.1; only webhook receiver is externally exposed
      (via reverse proxy + TLS if exposed).

## Operations
- [ ] Docker: run containers as non-root (`-u $(id -u):$(id -g)`) so wallet files are
      kon-owned.
- [ ] Healthcheck on merchant container (`/healthz`); restart policy set.
- [ ] Disk headroom: 97% full — clean Docker build cache before merchant build
      (`docker builder prune`), watch `df` during cargo build.
- [ ] Failure matrix documented in DEVELOPER.md §8 (unpaid work, double-payment,
      sync stuck, node unreachable, daemon down).
