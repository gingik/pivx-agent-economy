# pivx-agent-economy

**Self-hosted PIVX payment stack for AI agents.** A dockerized merchant daemon,
HMAC webhook receiver, wallet recovery tooling, task-marketplace runner, and
status dashboard — so an AI agent can hold a wallet, sell a verified output, and
get paid on-chain in PIV, unattended.

**Status: M0/M1/M2 foundation built and running live** (2026-08). Built by
[Kon / iotgrowsolutions.com](https://iotgrowsolutions.com).

---

## Why

AI agents increasingly do real, verifiable work — monitoring, alerting, data
collection. Paying for that work today requires a human in the loop (invoices,
cards, bank transfers) or centralized platform accounts agents cannot natively
hold.

PIVX provides the missing primitive: a live proof-of-stake chain with
zk-SNARK SHIELD privacy, ~60s block times, near-zero fees, and an official
**agent kit** (CLI + MCP server) purpose-built so agents can hold a wallet and
transact programmatically.

This repo is a complete, working merchant side: **agent-as-merchant** — sell a
verified output, get paid in PIV, provably.

## Features

- **Merchant daemon** (dockerized `pivx-merchant-kit`, loopback-mapped
  `127.0.0.1:7474`) — invoice creation, transparent payment detection, webhook
  delivery queue with HMAC signing and retries
- **Webhook receiver** (stdlib Python, no deps) — HMAC-verified
  (`X-Merchant-Signature`), idempotent on `X-Merchant-Delivery-Id`, triggers
  delivery of the paid-for output
- **Buyer-side proof** — every delivered output carries a `sign-message`
  signature over `(alert-hash + invoice-id + timestamp)`, verifiable with any
  PIVX Core `verifymessage`
- **SQLite ledger** — orders + task rewards with txids, memo-based audit trail
- **Task-marketplace runner** — signup → work → submit → reward verification on
  the live PIVX Tasks board, with human-in-the-loop gates and failure paths
- **Wallet recovery tooling** — `wallet-recover.sh` (fresh data dir + seed
  import + address verification), recovery drills in the test plan
- **Status dashboard** (Flask :5030, basic auth) — daemon health, wallet
  balance, invoice/payment history, webhook ledger, log tail
- **Upstream bugfixes as patches** — see [Patches](#patches)

## Architecture

```
                         ┌────────────────────────────────────────────┐
                         │               Host (Ubuntu)                │
                         │                                            │
  buyer / payer          │   ┌──────────────┐      ┌───────────────┐  │
 ──PIV payment──────► PIVX chain ──┬─►   pivx-merchant daemon  │  │
   (transparent)                   │   (docker, :7474 loopback)│  │
                                   │            │  ▲            │  │
                                   │            ▼  │ HMAC webhook│  │
                                   │   ┌───────────────────┐    │  │
                                   │   │ webhook receiver  │    │  │
                                   │   │ (:8081, stdlib)   │    │  │
                                   │   └─────────┬─────────┘    │  │
                                   │             │ trigger      │  │
                                   │             ▼              │  │
                                   │   agent: compose output,   │  │
                                   │   sign-message, deliver    │  │
                                   │   to buyer (+ ledger row,  │  │
                                   │   Telegram alert)          │  │
                                   │                            │  │
                                   │   dashboard (Flask :5030)  │  │
                                   │   ledger.db (SQLite)       │  │
                                   └────────────────────────────┘
```

Chain access: transparent = Blockbook (`utxos_for_address` polling per open
invoice); shield = compact sync via public PivxNodeController RPC.
**No chain download** — API binds immediately, `/healthz` answers instantly.

## Repository layout

```
config/         Dockerfile.merchant, merchant-config.toml, ledger-schema.sql,
                mcp-hermes.json, n8n-task-workflow.json, agents.json
patches/        0001-fix-stdin-passphrase-env-fallback.patch
                0002-shield-sync-gate.patch
                0003-mempool-height-backfill.patch
scripts/        merchant-webhook-receiver.py, merchant-dashboard.py,
                start-webhook-receiver.sh, wallet-recover.sh, wallet-backup.sh,
                task-runner.sh, enforce-limits.sh, ledger.py, pivutil.py,
                canary-scan.py, daily-digest.py, mcp-bridge.py, tests
docs/           test-plan.md, security-checklist.md
DEVELOPER.md    master build instructions (spec, verified facts, pitfalls)
GOAL.md         goal definition & success criteria
```

## Quickstart

**1. Build the merchant daemon** (vendored upstream source required — the
Dockerfile COPY expects `vendor/pivx-merchant-kit/`):

```sh
cd ~/github/pivx-agent-economy
git clone --depth 1 https://github.com/PIVX-Labs/pivx-merchant-kit.git vendor/pivx-merchant-kit
git -C vendor/pivx-merchant-kit apply ../patches/0001-fix-stdin-passphrase-env-fallback.patch
git -C vendor/pivx-merchant-kit apply ../patches/0002-shield-sync-gate.patch
git -C vendor/pivx-merchant-kit apply ../patches/0003-mempool-height-backfill.patch
docker build -f config/Dockerfile.merchant -t pivx-merchant:dev .
```

**2. Configure** — `config/merchant-config.toml` (copy to
`~/.config/pivx-merchant/merchant-config.toml`), unlock passphrase via
`--env-file` (patched `MERCHANT_KIT_UNLOCK_PASSPHRASE`, **no `-i` needed**),
generate an `auth_token`.

**3. Run the daemon:**

```sh
docker run -d --name pivx-merchant --restart unless-stopped \
  --env-file ~/.config/pivx-merchant/unlock.env \
  -v pivx-merchant-data:/app/data \
  -v ~/.config/pivx-merchant/merchant-config.toml:/app/config.toml:ro \
  --add-host host.docker.internal:host-gateway \
  -p 127.0.0.1:7474:7474 pivx-merchant:dev
```

**4. Run the webhook receiver** (host process; one-time firewall rule — ufw
drops docker0→host INPUT by default):

```sh
sudo ufw allow in on docker0 to any port 8081 proto tcp
PORT=8081 BIND_ADDR=0.0.0.0 scripts/start-webhook-receiver.sh
```

**5. Run the dashboard** (`scripts/start-merchant-dashboard.sh`) and open
`http://<host>:5030` (basic auth).

Then: `POST /v1/invoices` with an `external_id`, pay the invoice address, watch
`invoice.confirmed` fire in the receiver log. See `docs/test-plan.md` for the
full E2E path.

## Patches

Three upstream fixes, each with a documented root cause:

| Patch | Fix |
|---|---|
| `0001` | `MERCHANT_KIT_UNLOCK_PASSPHRASE` was dead code — `has_piped_stdin()` returns true for closed stdin, so `run` failed with *no unlock passphrase provided*; with `-i`+`-d` the daemon hung. Env-file unlock now works without `-i`. |
| `0002` | Shield sync gate — wallet-kit v0.2.2 compact parser expects lightwalletd framing (LE cmu, 724-byte outputs); public RPCs serve BE cmu + 756-byte outputs, so every shield tick failed `invalid cmu` after re-downloading ~36MB (≈35s/tick, API stalled behind the wallet mutex). `shield_enabled = false` skips shield entirely for transparent-only deployments. |
| `0003` | Mempool height backfill — Blockbook reports `height = 0` for mempool UTXOs; two upstream bugs (watchlist dropping `Confirming` invoices + silent duplicate-UTXO no-op) froze invoices in `Confirming` forever even at 25+ confirmations. Patch keeps `Confirming` watched and backfills the mined height (guarded to `block_height = 0` rows; reorgs stay the sweep's job). |

## Configuration highlights

- `[payments] accept = "transparent"`, `confirmations = 3`,
  `default_expiry_secs = 1800` — transparent default: ≈0.00002 PIV/tx vs
  ≈0.024 PIV for SHIELD (privacy premium, documented option, not default)
- `[sync] rpc_url = "https://rpc.pivxla.bz/mainnet"` +
  `explorer_url = "https://explorer.pivxla.bz"` — public endpoints verified
  against the kit's exact call patterns
- `[webhooks]` HMAC secret, `max_attempts = 10`, retry queue
- `[api]` binds container-side `0.0.0.0:7474` (docker-proxy dials the
  container eth0), host mapping keeps it loopback-only

## Testing

```sh
python3 scripts/test_receiver.py     # webhook HMAC/dedupe/injection
python3 scripts/test_helpers.py      # ledger + helper units
python3 scripts/test_canary.py       # secret-material canary scan
```

Plus the live E2E proof: a 1.0 PIV test invoice (`hermes-test-002`) confirmed
on-chain (txid `bb8bfeaa3ee231ec52a233fafb49b3c9b57f40334474303cd5d4f577da06bc67`),
`invoice.confirmed` webhook fired, ledger row written.

## Security

- Wallet file is **device-encrypted** (key = SHA256(machine-id + data-dir-path
  + salt)); the paper seed (`export`, run by the operator only, offline) is the
  only portable backup — see `scripts/wallet-recover.sh`
- No seed material in logs; `canary-scan.py` greps every log surface
- Webhooks HMAC-verified + idempotent; unknown paths 501/401
- Basic auth on the dashboard; daemon API loopback-mapped
- Full list: `docs/security-checklist.md`

## Roadmap

- **M0 — Foundation (done):** wallet provisioning, MCP `serve` (30 tools),
  task-runner, merchant daemon, ledger, docs
- **M1 — Marketplace proof:** complete paid task-board bounties end-to-end
  (in progress — live PIVX Tasks board)
- **M2 — Merchant prototype (done):** external payer → PIV → verified output,
  live with test invoice
- **M3 — Hardening/scale:** multi-agent, spend limits, posting our own
  bounties, daily digest, failure matrix

## Docs

- [GOAL.md](GOAL.md) — problem, success criteria, milestones
- [DEVELOPER.md](DEVELOPER.md) — master build instructions with verified facts
- [docs/test-plan.md](docs/test-plan.md) — test plan incl. recovery drill
- [docs/security-checklist.md](docs/security-checklist.md) — security checklist

## License

MIT — see [LICENSE](LICENSE).
