# 部署

部署分兩部分：

- Futu OpenD 用 Docker 跑。
- 呢個 repo 用 `uv` 喺 host 跑，連去 `127.0.0.1:11111` 嘅 OpenD。

## 1. 準備 Server

安裝 Docker、Docker Compose、Git 同 `uv`：

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git docker.io docker-compose inetutils-telnet openssl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

啟用 Docker：

```sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

加咗自己入 `docker` group 之後，要 logout 再 login。

## 2. 部署 App

Clone repo：

```sh
mkdir -p ~/projects
cd ~/projects
git clone <REPO_URL> algo-trading
cd algo-trading
```

安裝 dependencies：

```sh
uv sync
```

為 OpenD 建 RSA key。呢條 key 會 mount 入 container，同時留喺 host 供加密 API fallback 使用。

```sh
mkdir -p ~/futu-opend
openssl genrsa -out ~/futu-opend/futu.pem 1024
```

建立 runtime env file：

```sh
cp .env.example .env
vim .env
```

```sh
FUTU_ACCOUNT_ID=replace-me
FUTU_ACCOUNT_PWD_MD5=replace-me
FUTU_OPEND_IP=127.0.0.1
FUTU_OPEND_RSA_MOUNT=/root/futu-opend/futu.pem
```

Linux 計 Futu 密碼 MD5：

```sh
echo -n 'your-futu-password' | md5sum | awk '{print $1}'
```

唔好 commit `.env`。

## 3. 啟動 Futu OpenD

啟動 OpenD：

```sh
docker-compose pull futu-opend
docker-compose up -d futu-opend
```

`docker-compose.yml` 用 host networking，所以 app 會用 `127.0.0.1:11111` 連 OpenD。named volume 會保留登入 session，通常只係第一次登入、轉 account、或者 Futu 失效 device whitelist 時先要再做 SMS 驗證。

睇 log：

```sh
docker-compose logs -f futu-opend
```

睇 container 狀態：

```sh
docker ps --format "table {{.Names}}\t{{.Status}}"
```

如果 OpenD 要 SMS 驗證：

```sh
echo "input_phone_verify_code -code=123456" | telnet localhost 22222
```

如果 OpenD 要圖片驗證碼：

```sh
docker cp futu-opend-docker:/home/futu/.com.futunn.FutuOpenD/F3CNN/PicVerifyCode.png ./PicVerifyCode.png
echo "input_pic_verify_code -code=abcd" | telnet localhost 22222
```

跑策略前，先完成 OpenD 登入同設定。`.env` 同 `~/futu-opend/futu.pem` 要保密。

## 4. 基本測試

確認 host 連到 OpenD：

```sh
nc -z 127.0.0.1 11111
```

Dry-run 策略，唔落單：

```sh
uv run python main.py \
  --futu-host 127.0.0.1 \
  --futu-port 11111
```

落模擬盤 order 測試：

```sh
uv run python main.py \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --execute
```

如果想先取消 bot journal 記錄過嘅 open orders，再落模擬盤：

```sh
uv run python main.py \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --cancel-open-orders \
  --execute
```

預設係 market order。如果想用 normal limit order，用 `--order-type NORMAL`。

## 5. OpenD 疑難排解

如果 app 出 `RemoteClose`、`Disconnect context`，或者查唔到 account info，先檢查 OpenD：

```sh
docker ps --filter name=futu-opend-docker
docker-compose logs --tail 100 futu-opend
```

確認 host reach 到 OpenD：

```sh
nc -vz 127.0.0.1 11111
```

常見原因：

- OpenD container 未開。
- OpenD 未完成登入。
- SMS 驗證等緊 telnet port `22222` 輸入。
- 圖片驗證碼等緊處理。
- `FUTU_ACCOUNT_ID` 或 `FUTU_ACCOUNT_PWD_MD5` 錯。
- OpenD container 唔係用 host networking 啟動。
- 用 host networking 時，`FUTU_OPEND_IP` 唔係 `127.0.0.1`。

如果要 SMS：

```sh
echo "input_phone_verify_code -code=123456" | telnet localhost 22222
```

如果要 CAPTCHA：

```sh
docker cp futu-opend-docker:/home/futu/.com.futunn.FutuOpenD/F3CNN/PicVerifyCode.png ./PicVerifyCode.png
echo "input_pic_verify_code -code=abcd" | telnet localhost 22222
```

## 6. 停止開關

建立呢個 file 會阻止落單：

```sh
touch STOP_TRADING
```

刪走就可以恢復：

```sh
rm STOP_TRADING
```

`trade_journal.json` 會保存已提交同已取消 order。換 server 或重新部署前可以先備份。

## 7. Daily Cron Job

每日 runner 會啟動 Futu OpenD，等 API port ready，落模擬盤 order，完成後停止 Futu OpenD。呢個 project 無真錢交易 path。

Runner 跑緊嘅策略 = 闊池 S&P 500 動量集中（STRATEGY.md §9）：由 root 嘅 `sp500_constituents.csv`（成個 S&P 500）揀 126 日動量最強 top10、等權、QQQ 托底、**無槓桿**。信號 + 最新價用 **yfinance**（避開 Futu 歷史 K 線 60 次/30 秒頻率限制同每月配額），Futu 只負責查帳戶/持倉 + 落模擬單。Runner 內部按 `REBALANCE`（預設 monthly）gate：每月先換 basket，其餘日子 no-op，所以可以日日 cron 唔會 churn。

部署後設定 executable：

```sh
chmod +x scripts/daily_trade.sh
```

測試 cron 行為：

```sh
scripts/daily_trade.sh
```

安裝 cron job：

```sh
crontab -e
```

```cron
0 22 * * * cd /root/projects/algo-trading && /root/projects/algo-trading/scripts/daily_trade.sh >> /root/projects/algo-trading/logs/daily_trade.log 2>&1
```

檢查 cron 同 log：

```sh
crontab -l
tail -f logs/daily_trade.log
```

上面例子用 server local time。若 server 係 HKT，`0 22 * * *` 即係每日香港時間 22:00 跑。

Runner 支援以下 env override：

策略 / universe：

- `SP500_CSV`（S&P 500 list 路徑，預設 `$APP_DIR/sp500_constituents.csv`）
- `TOP_N`（持倉數量，預設 10）
- `INDEX_FLOOR`（空位托底 symbol，預設 QQQ）
- `LOOKBACK_DAYS`（動量回望，預設 126）
- `REBALANCE`（換 basket 頻率 daily/weekly/monthly，預設 monthly）
- `PRICE_SOURCE`（信號 + 最新價來源 yfinance/futu，預設 yfinance）

連線 / 風控：

- `FUTU_HOST`、`FUTU_PORT`
- `READY_TIMEOUT_SECONDS`（等 OpenD ready 上限，預設 180）
- `MAX_DAILY_ORDERS`（預設 40）
- `MAX_DAILY_NOTIONAL`（預設 5000000）
- `MAX_SINGLE_ORDER_NOTIONAL`（預設 1000000）

> `MAX_DAILY_NOTIONAL` 預設調高到 5M：闊池 top10 basket 喺百萬級戶口，月度全換倉（賣舊買新）notional 可達 ~2M，1M 會唔夠落單。

## 8. 更新部署

```sh
cd ~/projects/algo-trading
git pull
uv sync
uv run python -m compileall main.py algo_trading scripts
chmod +x scripts/daily_trade.sh
```

如果要更新 OpenD image：

```sh
docker-compose pull futu-opend
docker-compose up -d futu-opend
```

Compose 會喺 image 改變時重建 container。

如果要強制重新登入 OpenD，先停 container，再刪 volume：

```sh
docker-compose down
docker volume rm futu-opend-data
docker-compose up -d futu-opend
```
