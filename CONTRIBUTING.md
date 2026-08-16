# Contributing

Thanks for your interest in pivx-agent-economy. This is a small, focused
project with strong opinions about reproducibility — read the conventions
below before opening a PR.

## Project conventions (hard rules)

1. **Every shell command in docs is written in full.** No ellipses, no `…`,
   no "and so on". A new developer must be able to copy-paste every command.
2. **No heredocs.** File-based scripting only. If a script needs generated
   content, write a committed helper that produces it at runtime — never
   inline `cat <<EOF` in the terminal or in a doc.
3. **Secrets never appear.** Use the `[REDACTED]` marker + key name + length
   (e.g. `auth_token = [REDACTED]`). No private keys, seed phrases, or tokens
   in logs, chat, tool output, or committed files. `.env`-style files are
   `0600` and never committed.
4. **No PII in the ledger.** Ledger rows carry txids and addresses only.

## Getting started

```sh
cd ~/github/pivx-agent-economy
python3 scripts/test_receiver.py
python3 scripts/test_helpers.py
python3 scripts/test_canary.py
```

All three suites must pass before a PR. The canary test scans log surfaces for
seed material — a failure there blocks the merge.

## Patches (upstream fixes)

Upstream `pivx-merchant-kit` bugs are fixed as **patches**, not forks:

1. Patch files live in `patches/` with the format
   `NNNN-short-description.patch` (zero-padded sequence number).
2. Every patch has a header comment documenting the **root cause** and the
   **observed symptom** (see `0001`/`0002`/`0003` for the expected standard).
3. Apply order matters — patches are applied in sequence via:

```sh
git -C vendor/pivx-merchant-kit apply ../patches/0001-fix-stdin-passphrase-env-fallback.patch
git -C vendor/pivx-merchant-kit apply ../patches/0002-shield-sync-gate.patch
git -C vendor/pivx-merchant-kit apply ../patches/0003-mempool-height-backfill.patch
```

4. When you bump the upstream pin, re-verify each patch still applies and
   update DEVELOPER.md's verified-facts table.
5. If an upstream release fixes a patched bug, mark the patch
   `SUPERSEDED` in its header and note the upstream version.

## Adding or changing scripts

- stdlib-only where possible (the webhook receiver has zero dependencies by
  design — keep it that way).
- Ship a test alongside: `test_<name>.py` with the same name as the script.
- Update `docs/test-plan.md` when behaviour changes; update `DEVELOPER.md`
  verified-facts table when a claim is re-verified.
- Log to stderr for progress, stdout for JSON (mirrors the kit's behaviour).

## PR checklist

- [ ] `python3 scripts/test_receiver.py` passes
- [ ] `python3 scripts/test_helpers.py` passes
- [ ] `python3 scripts/test_canary.py` passes (no seed material anywhere)
- [ ] Commands in docs written in full, copy-pasteable
- [ ] No secrets, no PII; `[REDACTED]` convention respected
- [ ] Vendor patches: header documents root cause + symptom
- [ ] DEVELOPER.md verified-facts table updated if you changed claims

## Reporting issues

Include: what you ran (full command), the exact output, and the section of
DEVELOPER.md or the test plan that's wrong. Screenshots are welcome; redact
anything that looks like a key or address you don't want public.
