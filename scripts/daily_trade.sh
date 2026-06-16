#!/usr/bin/env sh
set -eu

APP_DIR="${APP_DIR:-/root/projects/algo-trading}"
LOG_DIR="${LOG_DIR:-$APP_DIR/logs}"
FUTU_HOST="${FUTU_HOST:-127.0.0.1}"
FUTU_PORT="${FUTU_PORT:-11111}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-180}"

# 策略 = 闊池 S&P 500 126 日動量揀 top10、等權、QQQ 托底、無槓桿（STRATEGY.md §9）。
# 信號 + 最新價用 yfinance（避開 Futu 歷史 K 線 60 次/30 秒限制同每月配額），
# Futu 只負責查帳戶/持倉 + 落模擬單。
SP500_CSV="${SP500_CSV:-$APP_DIR/sp500_constituents.csv}"
TOP_N="${TOP_N:-10}"
INDEX_FLOOR="${INDEX_FLOOR:-QQQ}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-126}"
REBALANCE="${REBALANCE:-monthly}"
PRICE_SOURCE="${PRICE_SOURCE:-yfinance}"

mkdir -p "$LOG_DIR"
cd "$APP_DIR"

if [ ! -f "$SP500_CSV" ]; then
	echo "搵唔到 S&P 500 list：$SP500_CSV" >&2
	exit 1
fi

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

# S&P 500 symbol list（CSV 第一欄，跳過 header）。
SYMBOLS="$(tail -n +2 "$SP500_CSV" | cut -d, -f1 | tr '\n' ' ')"

log "執行模擬交易計劃（闊池 top${TOP_N} + ${INDEX_FLOOR} 托底，無槓桿，${PRICE_SOURCE} 信號）"
# shellcheck disable=SC2086  # $SYMBOLS 要 word-split 成多個 --symbols 參數。
uv run python main.py \
	--symbols $SYMBOLS \
	--price-source "$PRICE_SOURCE" \
	--futu-host "$FUTU_HOST" \
	--futu-port "$FUTU_PORT" \
	--execute \
	--top-n "$TOP_N" \
	--index-floor "$INDEX_FLOOR" \
	--lookback-days "$LOOKBACK_DAYS" \
	--rebalance "$REBALANCE" \
	--state-path strategy_state.json \
	--cancel-open-orders \
	--max-daily-orders "${MAX_DAILY_ORDERS:-40}" \
	--max-daily-notional "${MAX_DAILY_NOTIONAL:-5000000}" \
	--max-single-order-notional "${MAX_SINGLE_ORDER_NOTIONAL:-1000000}"
