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
	log "停止 Futu OpenD"
	docker-compose stop futu-opend
}

trap stop_opend EXIT INT TERM

log "啟動 Futu OpenD"
docker-compose up -d futu-opend

log "等待 Futu OpenD API port ready"
deadline=$(($(date +%s) + READY_TIMEOUT_SECONDS))
while :; do
	if nc -z "$FUTU_HOST" "$FUTU_PORT"; then
		break
	fi

	if [ "$(date +%s)" -ge "$deadline" ]; then
		log "Futu OpenD 喺 ${READY_TIMEOUT_SECONDS}s 內都未 ready"
		exit 1
	fi

	sleep 10
done

log "執行模擬交易計劃"
uv run python main.py \
	--futu-host "$FUTU_HOST" \
	--futu-port "$FUTU_PORT" \
	--execute \
	--symbols NVDA TSM AVGO MSFT GOOG AMZN MU COIN MRK NBIS NDAQ HOOD IBM AXP HON AAPL ETN JPM GEV IBKR \
	--top-n 2 \
	--cancel-open-orders \
	--max-daily-orders "${MAX_DAILY_ORDERS:-20}" \
	--max-daily-notional "${MAX_DAILY_NOTIONAL:-1000000}" \
	--max-single-order-notional "${MAX_SINGLE_ORDER_NOTIONAL:-1000000}"
