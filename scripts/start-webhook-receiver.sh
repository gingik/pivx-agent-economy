#!/bin/sh
# start-webhook-receiver.sh — launch the pivx-merchant webhook receiver (sell side).
# Host process (NOT in docker): the merchant container reaches it via
# host.docker.internal (host-gateway on the docker0 bridge).
#
# Reads secrets at runtime — nothing hardcoded here:
#   TELEGRAM_BOT_TOKEN / TELEGRAM_HOME_CHANNEL  <- ~/.hermes/.env
#   [webhooks].secret                           <- live merchant config (0600)
#
# Usage:
#   PORT=8081 BIND_ADDR=0.0.0.0 ./start-webhook-receiver.sh
# (BIND_ADDR=0.0.0.0 so the container's docker0-bridge connection lands;
#  the /webhook route is HMAC-verified, other paths 404.)

ENV_FILE="${HERMES_ENV:-$HOME/.hermes/.env}"
CFG="${MERCHANT_CONFIG:-$HOME/.config/pivx-merchant/merchant-config.toml}"

TG_TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
TG_CHAT="$(grep -E '^TELEGRAM_HOME_CHANNEL=' "$ENV_FILE" | cut -d= -f2-)"
[ -n "$TG_CHAT" ] || TG_CHAT=328267004
WH_SECRET="$(awk -F'"' '/^secret = /{print $2}' "$CFG")"

export TELEGRAM_BOT_TOKEN="$TG_TOKEN" TELEGRAM_CHAT_ID="$TG_CHAT"
export WEBHOOK_SECRET="$WH_SECRET"

exec python3 "$(dirname "$0")/merchant-webhook-receiver.py"
