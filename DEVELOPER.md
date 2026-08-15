# DEVELOPER.md — PIVX Agent-to-Agent Payments: Master Build Instructions

**Project:** `pivx-agent-economy` · **Owner:** Kon (iotgrowsolutions.com)
**Status:** Under construction — M0 foundation built. See TODO markers for what's next.
**Requirement source:** `GOAL.md` (§3 success criteria, §6 milestones). This doc maps
each build step to those criteria. Every shell command is shown in full; secrets are
`[REDACTED]` with key names + lengths only.

---

## 0. Environment truth (verified 2026-08-15)

| Fact | Value |
|---|---|
| Host | Ubuntu 22.04, glibc 2.35, kernel 5.15 |
| Disk | 97% full (2.2 GB free on /) — **no Rust toolchain, no source builds** |
| Docker | Available; image builds OK |
| pivx-agent-kit | **v0.6.0**, runs via Docker wrapper (pre-built binary needs glibc 2.39) |
| pivx-merchant-kit | **v0.1.0**, upstream cloned at `/tmp/pivx-merchant-kit` (source only, no image) |
| CLI wrapper | `/home/kon/.local/bin/pivx-agent-kit` (docker run --rm -i) |
| Wallet data root | `~/.local/share/pivx-agent-kit/<agent>/` (one dir per agent) |
| Ledger | SQLite, `~/.local/share/pivx-agent-kit/ledger.db` (beside wallet data) |

### Kit facts (from source, verified)
- One seed = one SHIELD (`ps1…`) + one transparent (`D…`) address. **No HD sub-address
  exposure** → per-agent wallets = per-agent data dirs.
- Wallet file is **device-encrypted**: key = SHA256(machine-id + data-dir-path + salt)
  (`src/wallet.rs`). The container mounts the **host** `/etc/machine-id:ro` so the key
  anchors to this machine. The wallet file is therefore NOT portable — **the paper seed
  is the real backup** (see §3).
- MCP server is **stdio-only** JSON-RPC (`serve`). Hermes can spawn it natively; n8n
  cannot — use Execute Command (see §5).
- `sign-message` signs with the transparent key; sig is base64, verifiable by any
  PIVX Core `verifymessage` — this is the buyer-side proof for M2.
- `send <addr> <amount> --from <public|private> [memo]`. Memo only works shield→shield.
- `task` subcommands: list/search/get/profile (read); signup/submit (worker);
  create/approve/reject/cancel (creator); notifications (inbox).

### Conventions
- Every shell command in this repo is written in full. No ellipses.
- Secrets: `[REDACTED]` + key name + length. Never in logs/chat.
- No heredocs (blocked). File-based scripting only.
- Kon runs sudo, sensitive downloads, and the merchant-kit build himself.
- Tor SOCKS5 `:9050` available for privacy-sensitive polling if needed.

---

## 1. CLI wrapper (per-agent data dirs)

`~/.local/bin/pivx-agent-kit`:
```sh
#!/bin/sh
# pivx-agent-kit wrapper: runs v0.6.0 in a minimal Ubuntu 24.04 container.
AGENT="${PIVX_AGENT:-hermes-main}"
DATA_ROOT="$HOME/.local/share/pivx-agent-kit"
AGENT_DIR="$DATA_ROOT/$AGENT"
mkdir -p "$AGENT_DIR"
# shellcheck disable=SC2086
exec docker run --rm -i \
  -u "$(id -u):$(id -g)" \
  -v "$AGENT_DIR:/data/pivx-agent-kit" \
  -v /etc/machine-id:/etc/machine-id:ro \
  -e XDG_DATA_HOME=/data \
  -e HOME=/data \
  pivx-agent-kit "$@"
```

**Key properties:**
- `PIVX_AGENT` selects the agent (default `hermes-main`) → per-agent wallet isolation.
- `-u $(id -u):$(id -g)` → wallet files owned by kon, not root.
- Host machine-id mounted `:ro` → device-bound encryption is stable across container
  runs AND image rebuilds (fixes: empty container machine-id made the key derive from
  "" + path, which was portable-but-unstable; now truly device-bound).
- Container-side path `/data/pivx-agent-kit` never changes → key derivation stable.

---

## 2. Wallet provisioning (M0, per-agent)

Procedure for EACH agent (repeat with `PIVX_AGENT=<name>`):

```sh
# 1. create wallet (idempotent — errors if wallet exists)
pivx-agent-kit init
# 2. record addresses into config/agents.json (DO NOT skip)
pivx-agent-kit address
# 3. Kon: paper-seed backup BEFORE funding (see §3)
pivx-agent-kit export        # run by Kon only, offline, output never logged
# 4. fund the TRANSPARENT address (5–10 PIV float recommended)
pivx-agent-kit balance       # verify non-zero after funding
```

**Done (M0):** `hermes-main` provisioned 2026-08-15:
- shield: `ps1hpamhcrgumpt2lq6hh60y4522d986n44ktgd5jxqzge5ll8kdxfm53ne8he0c7cpajvk7gfstjq`
- transparent: `DEd1j7RYyu8RVxLbBV4swKS3abwYQsyVoi` (⚠ **NOT yet funded** — awaiting
  Kon's paper-seed backup, per §3, before any money moves)
- `~/.local/share/pivx-agent-kit/hermes-main/wallet.json` (0600, kon-owned)

**TODO(M0):** Kon does `pivx-agent-kit export` → paper backup → confirm in chat.
**TODO(M0):** Kon funds transparent address; `balance` verified.

---

## 3. Backup & recovery

**Backup truth:** the wallet file is device-encrypted and NOT a backup. The only
portable backup is the **seed phrase** (`export`). Recovery = fresh data dir + `import`.

- `scripts/wallet-backup.sh` — verifies wallet.json exists, perms are 0600, prints the
  "paper seed" reminder. Exports nothing (export is Kon's hands-on step).
- `scripts/wallet-recover.sh <agent>` — creates a fresh data dir, prompts for the seed
  interactively (never on the command line), runs `import`, verifies addresses match
  `config/agents.json`. **Recovery drill is test-plan item #5 — run before real funds.**

---

## 4. MCP integration (M0)

### Hermes (stdio, native)
`config/mcp-hermes.json` — register one MCP entry per agent:
```json
{
  "mcpServers": {
    "pivx-hermes-main": {
      "command": "/home/kon/.local/bin/pivx-agent-kit",
      "args": ["serve"],
      "env": { "PIVX_AGENT": "hermes-main" }
    }
  }
}
```
The wrapper passes `serve` through; the agent's data dir comes from `PIVX_AGENT`.

### n8n (no stdio support → Execute Command)
n8n runs in Docker and cannot spawn stdio servers on the host. Two options:

1. **RECOMMENDED — n8n "Execute Command" node** calling the CLI directly:
   `pivx-agent-kit task list --status open --limit 20` → JSON in/out, no long-lived
   process. Sample workflow: `config/n8n-task-workflow.json`.
2. **Alternative — stdio↔HTTP bridge** `scripts/mcp-bridge.py` (only if you need
   persistent tool sessions; not needed for the current flows).

### Verification (M0, done except funded items)
- `pivx-agent-kit balance` → `{"error": "No wallet found..."}` no longer (wallet exists)
- `pivx-agent-kit address` → addresses match agents.json ✓
- `pivx-agent-kit sign-message "test-alert-hash-abc123"` → base64 sig + address ✓
  (verified 2026-08-15; signature format matches PIVX Core `verifymessage` input)
- MCP `serve` handshake ✓ — `initialize` returns `serverInfo: pivx-agent-kit 0.6.0`,
  protocolVersion 2024-11-05. **30 tools** exposed (verified via bridge):
  `pivx_init/import/address/balance/send/resync/export/sign_message`,
  `pivx_task_list/search/get/profile/signup/submit/create/approve/reject/cancel/
  notifications/notification_read/notification_read_all/notification_dismiss`,
  `pivx_cards_regions/search/details/order_create/order_pay/order_check/
  order_cancel/order_list` (cards = PIVX gift-card marketplace, extra capability)
- `scripts/mcp-bridge.py` stdio↔HTTP bridge verified end-to-end (initialize +
  tools/list over HTTP) ✓
- **TODO(M0, post-funding):** dust self-transfer + `send --from public` + `balance`
  delta; sign-message round-trip against a public verifymessage (PIVX Core RPC
  `verifymessage` is exposed on public nodes; see §7 endpoint list).

### Pitfalls logged (fixes applied 2026-08-15)
- **`echo` mangles JSON**: `echo "$FILTERED"` interprets `\n` escapes inside JSON
  strings → always use `printf '%s' "$FILTERED"` when piping JSON in shell.
- **Kit JSON has raw control chars** in descriptions → parse with `strict=False`
  (`scripts/task_filter.py`).
- **Heredocs blocked in terminal** → file-based scripting; scripts use committed
  helper files, never inline `cat <<EOF` generation at runtime.
- **`balance` prints sync progress to stderr**, JSON to stdout → `2>/dev/null` when
  capturing.

---

## 5. Marketplace proof (M1) — task-runner

**Flow (per build plan):**
`task list --status open` → filter categories our agents can do unattended
(dev/social/research/content; **exclude** design/creative) → `task get <id>` →
`task signup <id>` → perform work → `task submit <id> <body> [files]` →
`task notifications --unread` (poll for approval/rejection) → on paid, verify
`balance` delta + record txid in ledger.

**Script:** `scripts/task-runner.sh <agent> [--dry-run]`
- Lists eligible open tasks, **alerts Kon on Telegram before signup** (human-in-the-loop
  gate for the first N tasks; N in config), then submits, journals every transition to
  the SQLite ledger (`task_rewards` table).
- Failure paths scripted: rejection → log reason, NO auto-retry; node/explorer
  unreachable → exponential backoff, Telegram alert after 3 failures; approved-but-
  unpaid → dispute note in ledger + alert.

**TODO(M1):** after funding, run `task-runner.sh hermes-main --dry-run` to validate
the board view; then first live signup with Kon's approval.

---

## 6. Merchant prototype (M2) — pivx-merchant-kit

### Build (Kon runs this — source build, disk heavy)
```sh
cd ~/github/pivx-agent-economy
git clone --depth 1 https://github.com/PIVX-Labs/pivx-merchant-kit.git   # if absent
docker build -f config/Dockerfile.merchant -t pivx-merchant-kit .
```
Build stage: `rust:latest` (glibc ≥ 2.39) `cargo build --release` (binary name
`pivx-merchant-kit`, entrypoint `run --config`). Runtime: Ubuntu 24.04, binary +
config + SQLite + Sapling params on one volume. **Fallback:** if the build fails
(disk/crates), revert to custom poller design (appendix A).

### Config
`config/merchant-config.toml` (derived from upstream `config.toml.example`):
- `[payments] accept = "transparent"` (decision: default channel transparent; shield
  optional — ~0.024 PIV shield fee vs ~0.00002 transparent), `confirmations = 3`,
  `default_expiry_secs = 1800`
- `[sync] rpc_url = "https://rpc.pivxla.bz/mainnet"` + `explorer_url =
  "https://explorer.pivxla.bz"` — **public endpoints verified by upstream docs**;
  re-verify reachability at deploy time (curl in §7)
- `[api] bind 127.0.0.1:7474`, `auth_token = [REDACTED]` (generate per deployment)
- `[webhooks] url` → local receiver, `secret = [REDACTED]` (HMAC), `max_attempts = 10`

### Flow (scripts + n8n workflow)
1. Buyer requests alert → backend `POST /v1/invoices` with `external_id = alert-order-id`
2. Buyer pays the invoice address (transparent)
3. Webhook `invoice.confirmed` → `scripts/merchant-webhook-receiver.py` verifies HMAC
   `X-Merchant-Signature`, dedupes on `X-Merchant-Delivery-Id`, triggers delivery
4. Fall-detection agent composes alert payload, runs `sign-message` over
   `(alert-hash + invoice-id + timestamp)`
5. Deliver alert + signature + transparent address to buyer; buyer verifies via any
   PIVX Core `verifymessage`
6. Ledger row written; Telegram alert sent

### Ledger (SQLite)
`~/.local/share/pivx-agent-kit/ledger.db`, schema in `config/ledger-schema.sql`:
- `orders` — id, external_id, invoice_id, amount_sat, payer_addr, status, txid,
  alert_hash, signature, created_at, confirmed_at
- `task_rewards` — task_id, handle, bounty_sat, txid, status, ts
- Note: memos only work shield→shield (transparent default → memo annotation
  unavailable; tracked as known limitation).

### M2 test path
1. Simulated second party: second kit wallet (`buyer-bot`, own data dir) pays a dust
   invoice → receiver log shows `invoice.confirmed`, ledger row, Telegram alert.
2. One real external payer (Kon's second wallet) with dust amount.

**TODO(M2):** Kon runs the merchant build; endpoint reachability curl; dust test.

---

## 7. Public PIVX endpoints (VERIFIED 2026-08-15)

**Both endpoints work with the merchant-kit's exact call patterns:**
```sh
# PIVX Core RPC shim (path-based routing, NOT standard JSON-RPC):
curl -s https://rpc.pivxla.bz/mainnet/getblockcount          # → 5542203 [200]
# Blockbook v2 explorer (inSync, PIVX Core 5.6.1):
curl -s https://explorer.pivxla.bz/api/v2/blockbook/status   # → [200]
```
The kit's `sync/http.rs` uses `GET /getblockcount` + raw-hex POST for
`/getshielddata` on the configured base — matches rpc.pivxla.bz exactly. Standard
JSON-RPC POST to `/mainnet` returns 405 (wrong shape, not a broken endpoint).
**Endpoints verified — no fallback needed.**

---

## 8. Hardening (M3)

- **Multi-agent:** provision `agent-2`, `agent-3` via §2 procedure; each gets its own
  MCP entry + ledger identity column.
- **Spend controls:** `scripts/enforce-limits.sh` wraps `send` — per-tx cap, daily cap,
  balance floor; deny + Telegram alert on breach (kit has no native limits).
- **Task creation:** `task create --title … --description … --category … --amount …`
  to post our own bounties; monitor via SQLite query → Telegram daily digest
  (`task_rewards` + `orders` summary). `scripts/daily-digest.py` sends the daily
  summary (cron `0 7 * * *` or n8n Schedule; env `TELEGRAM_BOT_TOKEN`/`CHAT_ID`).
- **Failure matrix:** unpaid work / double-payment (idempotent `external_id` + dedupe)
  / sync stuck (`resync` runbook) / node unreachable / merchant daemon down
  (healthcheck + restart policy).

---

## 9. Verification checklist (maps to GOAL.md §3)

| # | Check | Where |
|---|---|---|
| 1 | balance non-zero after funding; sign-message verifies via public PIVX verifymessage | §2, §4 |
| 2 | completed task row in ledger with txid resolvable on explorer | §5, §8 |
| 3 | webhook receiver log shows invoice.confirmed; buyer verifymessage passes; txid on explorer | §6 |
| 4 | 7-day unattended soak; Telegram success/failure alerts; zero seed-material canary hits in logs | §8, docs/test-plan.md |
| 5 | recovery drill: fresh data dir + import from paper seed reproduces addresses + balance | §3, docs/test-plan.md |
| 6 | merchant container /healthz 200; SQLite file present; dust invoice confirms | §6, docs/test-plan.md |

Security checklist: `docs/security-checklist.md` (wallet perms, export-by-Kon-only,
no secrets in logs, HMAC webhooks, no PII in ledger, Tor option).

---

## Appendix A — Fallback: custom transparent poller (if merchant build fails)

If `config/Dockerfile.merchant` build fails, revert to: Blockbook API (`explorer.pivxla.bz`)
transaction polling for an address per order; confirm after 3 blocks; same webhook
receiver, ledger, sign-message delivery flow. Loses: HD invoice addresses, auto-refunds,
HMAC webhook queue. Kept as appendix only — not the primary path.

## Appendix B — Cost note
Transparent tx ≈ 0.00002 PIV; SHIELD tx ≈ 0.024 PIV (privacy premium). Default
channel: transparent. Privacy option documented, not default.
