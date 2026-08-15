#!/usr/bin/env python3
"""Generate MERCHANT_DASH_USER/PASS for the dashboard.

Writes to ~/.hermes/.env (appended; read by the dashboard at startup)
and mirrors the pair to ~/.config/pivx-merchant/dashboard-creds.txt (0600)
so Kon can cat it. Prints nothing except the paths — never the values.
"""
import os
import secrets
import stat

ENV = os.path.expanduser("~/.hermes/.env")
CREDS = os.path.expanduser("~/.config/pivx-merchant/dashboard-creds.txt")

user = "kon"
pw = secrets.token_urlsafe(18)

# append to ~/.hermes/.env without echoing values
with open(ENV, "a") as f:
    if os.path.exists(ENV) and os.path.getsize(ENV) > 0:
        f.write("\n")
    f.write(f"MERCHANT_DASH_USER={user}\n")
    f.write(f"MERCHANT_DASH_PASS={pw}\n")

os.makedirs(os.path.dirname(CREDS), exist_ok=True)
with open(CREDS, "w") as f:
    f.write(f"user: {user}\npass: {pw}\n")
os.chmod(CREDS, stat.S_IRUSR | stat.S_IWUSR)

print(f"creds written to {CREDS} (and {ENV}) — nothing printed above")
