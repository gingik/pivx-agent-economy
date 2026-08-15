# Goal Definition — PIVX Agent-to-Agent Payments (AI Agent Economy)

**Project:** pivx-agent-economy
**Owner:** Kon (iotgrowsolutions.com)
**Status:** Draft for systems analyst → produces developer instructions
**Date:** 2026-08-15

---

## 1. Problem / Why

AI agents increasingly do real, verifiable work — monitoring, alerting, data
collection, content production. Today, paying for that work requires a human in
the loop (invoices, cards, bank transfers) or centralized platform accounts that
agents cannot natively hold.

PIVX provides the missing primitive: a live proof-of-stake chain with
zk-SNARK SHIELD privacy, ~60s block times, near-zero fees, and an official
**agent kit** (CLI + MCP server) purpose-built so AI agents can hold a wallet,
check balances, and send/receive payments programmatically.

**For iotgrowsolutions specifically:** agent work is currently a cost line
(agents monitor, we pay for infra). This project flips it into a revenue line:
an agent that produces a valuable output (e.g. verified fall-detection alerts
for seniors) gets **paid by an external party in PIV, per output, on-chain**.

## 2. Goal Statement (single sentence, measurable)

> Establish a production capability where PIVX-native agents transact with
> **external, untrusted counterparties** — completing paid work and getting paid
> on-chain — proven first by participating in the live PIVX Tasks marketplace,
> then by selling a real agent-produced service (agent-as-merchant) for PIV.

Internal-only agent payments are explicitly **not** a goal (moving PIV between
our own wallets creates no value beyond testing rails).

## 3. Success Criteria (definition of done)

1. One of our agents claims and completes a **paid task on the PIVX Tasks
   board** (`task signup` → work → `task submit` → reward received on-chain),
   reward verified via `balance`.
2. An **external party** (human or agent, not us) pays our agent for a
   verified output in PIV, end-to-end, with the payment provable on-chain and
   the output provable via `sign-message`.
3. The flow runs unattended: payment in → work verified → PIV credited, with
   alerts on success/failure (Telegram, consistent with existing bots).
4. No seed phrase or private key ever appears in logs, chat, or tool output;
   keys are device-bound and backed up per existing conventions.

## 4. Scope

### In scope
- Per-agent wallet provisioning (one wallet/identity per agent).
- MCP server integration: kit's `serve` exposed so Hermes/n8n agents hold
  `balance`, `address`, `send`, `sign-message` as native tools.
- PIVX Tasks participation: signup, work, submit, reward verification.
- Agent-as-merchant prototype: our fall-detection alert agent sells verified
  alerts; external payer → PIV payment → alert delivered.
- Payment audit trail: memo-based ledger of every agent transaction.
- Failure/alerting paths (Telegram), consistent with existing bots.

### Out of scope (explicitly)
- Smart contracts / on-chain programmability (PIVX has no EVM — all logic is
  off-chain; the chain provides value transfer + privacy + proof).
- Internal-only circular payments (rejected — see §1).
- Human-facing payment UX beyond what's needed for the prototype.
- Tax/compliance treatment (flagged for analyst, not built).
- Non-PIVX chains.

## 5. Existing Assets & Constraints (environment truth)

- PIVX Agent Kit **v0.6.0 installed and verified** — binary runs in a minimal
  Ubuntu 24.04 Docker container (host GLIBC 2.35 too old for pre-built
  releases; no Rust toolchain; disk 97% full → no local Rust builds).
  Wrapper: `~/.local/bin/pivx-agent-kit`; wallet data on host at
  `~/.local/share/pivx-agent-kit/` (bind-mounted).
- Commands verified working: `task list/search/get`, `balance` (clean
  "no wallet" error), full CLI help. Wallet NOT yet initialized.
- Live PIVX Tasks board exists today (open bounties: Edge Wallet 2 PIV, etc.).
- Host stack: Hermes agent (Telegram), n8n in Docker (Postgres), cron jobs,
  IoT products (fall detection LOLIN32+MPU-6050, irrigator, grow tent), Tor
  SOCKS5 :9050 available for privacy-sensitive traffic.
- Developer (Hermes) constraints: no heredocs/execute_code in this session;
  file-based scripting only; every shell command displayed in full.
- Operator (Kon) does sudo and sensitive downloads himself; secrets never
  stored/shown ([REDACTED] convention).

## 6. Suggested Milestones (analyst to refine)

- **M0 – Foundation:** `init` wallet; per-agent address scheme; `serve` wired
  into Hermes MCP; `balance`/`send` working from agent context.
- **M1 – Marketplace proof:** agent completes ≥1 paid task-board bounty
  end-to-end with on-chain reward. (Proves: identity, task lifecycle,
  reward flow, unattended operation.)
- **M2 – Merchant prototype:** fall-detection alert agent: external payer
  sends PIV → agent verifies payment → delivers signed alert → ledger entry.
  Start with a simulated second party, then a real one.
- **M3 – Hardening/scale:** multiple agents, memo-ledger dashboard, task
  creation (posting bounties), failure modes, monitoring.

## 7. Open Questions for the Systems Analyst

1. **Wallet topology:** one wallet per agent vs. one shared wallet with
   per-agent derived addresses? (Deterministic derivation is likely right —
   analyst to decide and specify.)
2. **Key management:** where does the seed live (encrypted file, env, external
   vault)? Backup/restore procedure? Recovery drill?
3. **Payment verification (merchant flow):** how does the alert agent verify a
   payment arrived before delivering output (confirmation count, shield vs
   transparent, block scanning)? Escrow needed or pay-first-deliver-later?
4. **Output verification:** how does the *buyer* verify the alert is genuine
   (`sign-message` with agent's public key) and fresh?
5. **MCP integration:** exact mechanism to expose kit `serve` to Hermes and/or
   n8n (stdio vs SSE, auth, process lifecycle in Docker).
6. **Privacy posture:** which flows use SHIELD (private) vs transparent?
   (Fall-detection billing is sensitive data — SHIELD likely preferred for
   payment metadata.)
7. **Failure paths:** unpaid work, disputed submissions, double-payment,
   node unreachable, wallet sync stuck — each needs a defined response.
8. **Malta compliance:** does receiving PIV for services create taxable/AML
   obligations? (Flag for legal, not to block prototype.)
9. **Budget/limits:** per-agent spend caps, daily limits, alert thresholds.
10. **Task-board economics:** which bounty categories our agents can actually
    complete unattended (social tasks yes; design/creative no).

## 8. Deliverable Expected From the Analyst

Technical instructions for the developer covering, at minimum:

- Wallet provisioning spec (topology, key storage, backup, recovery).
- MCP serve integration steps for Hermes (and n8n if applicable).
- Task marketplace flow: exact command sequences + error handling.
- Merchant prototype design: API/flow diagram, payment verification logic,
  alert signing, ledger schema (SQLite? Postgres?).
- Test plan mapping to the 4 success criteria in §3.
- Security checklist (keys, logs, memos, [REDACTED] convention).
