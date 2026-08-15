#!/usr/bin/env python3
"""pivutil.py — exact PIV<->sat conversions (Decimal, no float loss).

Replaces `int(float(x) * 1e8)` math that silently dropped satoshis on large
amounts (bug list #8). The kit itself parses amounts as exact integers
(parse_piv_to_sat) — this matches that.

Subcommands:
  piv-to-sat <amount>         "0.12345678" -> 12345678 (exact)
  balance-to-sat [json]       sum of public_balance + private_balance in sat;
                              JSON from argv[1] or stdin (kit sync-progress
                              goes to stderr, JSON to stdout).

Stdlib only.
"""
import json
import sys
from decimal import Decimal, InvalidOperation

_SAT = Decimal(10 ** 8)


def piv_to_sat(piv) -> int:
    try:
        return int(Decimal(str(piv)) * _SAT)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"invalid PIV amount: {piv!r}") from e


def balance_to_sat(raw: str) -> int:
    # strict=False: kit JSON can contain raw control chars in strings.
    b = json.loads(raw, strict=False)
    pub = Decimal(str(b.get("public_balance") or 0))
    priv = Decimal(str(b.get("private_balance") or 0))
    return int((pub + priv) * _SAT)


def main(argv: list) -> int:
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "piv-to-sat":
        print(piv_to_sat(argv[1]))
    elif cmd == "balance-to-sat":
        raw = argv[1] if len(argv) > 1 else sys.stdin.read()
        print(balance_to_sat(raw))
    else:
        sys.stderr.write(f"pivutil.py: unknown subcommand '{cmd}'\n")
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
