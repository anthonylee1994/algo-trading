#!/usr/bin/env sh
set -eu

APP_DIR="${APP_DIR:-/root/projects/algo-trading}"
LOG_DIR="${LOG_DIR:-$APP_DIR/logs}"
FUTU_HOST="${FUTU_HOST:-127.0.0.1}"
FUTU_PORT="${FUTU_PORT:-11111}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-180}"

mkdir -p "$LOG_DIR"
cd "$APP_DIR"

log() {
  printf '%s %s\n' "$(date -Is)" "$*"
}

stop_opend() {
  log "Stopping Futu OpenD"
  docker-compose stop futu-opend
}

trap stop_opend EXIT INT TERM

log "Starting Futu OpenD"
docker-compose up -d futu-opend

log "Waiting for Futu OpenD"
deadline=$(( $(date +%s) + READY_TIMEOUT_SECONDS ))
while :; do
  if nc -z "$FUTU_HOST" "$FUTU_PORT"; then
    break
  fi

  if [ "$(date +%s)" -ge "$deadline" ]; then
    log "Futu OpenD did not become ready within ${READY_TIMEOUT_SECONDS}s"
    exit 1
  fi

  sleep 10
done

log "Executing simulated trading plan"
uv run python main.py \
  --futu-host "$FUTU_HOST" \
  --futu-port "$FUTU_PORT" \
  --execute \
  --cancel-open-orders \
  --max-daily-orders "${MAX_DAILY_ORDERS:-20}" \
  --max-daily-notional "${MAX_DAILY_NOTIONAL:-1000000}" \
  --max-single-order-notional "${MAX_SINGLE_ORDER_NOTIONAL:-1000000}"
