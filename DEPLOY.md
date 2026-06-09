# Deploy

Server deployment uses two parts:

- Futu OpenD runs in Docker.
- This repo runs with `uv` on the host and connects to OpenD on `127.0.0.1:11111`.

## 1. Prepare The Server

Install Docker, Git, and `uv`.

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git docker.io inetutils-telnet openssl
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Enable Docker:

```sh
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and back in after adding your user to the `docker` group.

## 2. Run Futu OpenD

Pull the OpenD image:

```sh
docker pull ghcr.io/manhinhang/futu-opend-docker:ubuntu-stable
```

Create an RSA key for OpenD:

```sh
mkdir -p ~/futu-opend
openssl genrsa -out ~/futu-opend/futu.pem 1024
```

Create an env file for the OpenD container:

```sh
vim ~/futu-opend/.env
```

```sh
FUTU_ACCOUNT_ID=replace-me
FUTU_ACCOUNT_PWD_MD5=replace-me
FUTU_OPEND_IP=127.0.0.1
```

Compute the password MD5 on Linux:

```sh
echo -n 'your-futu-password' | md5sum | awk '{print $1}'
```

Start OpenD. Use host networking so the host app connects as `127.0.0.1`;
otherwise OpenD treats trade API calls as cross-network traffic and requires
protocol encryption. The named volume keeps the login session across container
recreates, so SMS verification is usually only needed on first run, account
switch, or when Futu invalidates the device whitelist.

```sh
docker run -d \
  --name futu-opend-docker \
  --restart unless-stopped \
  --network host \
  --env-file ~/futu-opend/.env \
  -v ~/futu-opend/futu.pem:/.futu/futu.pem \
  -v futu-opend-data:/home/futu/.com.futunn.FutuOpenD \
  ghcr.io/manhinhang/futu-opend-docker:ubuntu-stable
```

Check logs:

```sh
docker logs -f futu-opend-docker
```

Check health:

```sh
docker ps --format "table {{.Names}}\t{{.Status}}"
```

If OpenD asks for SMS verification:

```sh
echo "input_phone_verify_code -code=123456" | telnet localhost 22222
```

If OpenD asks for picture CAPTCHA:

```sh
docker cp futu-opend-docker:/home/futu/.com.futunn.FutuOpenD/F3CNN/PicVerifyCode.png ./PicVerifyCode.png
echo "input_pic_verify_code -code=abcd" | telnet localhost 22222
```

Finish any required OpenD login/configuration before running real trades. Keep
`~/futu-opend/.env` and `~/futu-opend/futu.pem` private.

## 3. Deploy The App

Clone the repo:

```sh
mkdir -p ~/projects
cd ~/projects
git clone <REPO_URL> algo-trading
cd algo-trading
```

Install dependencies:

```sh
uv sync
```

Create the runtime env file:

```sh
cp .env.example .env
```

If `.env.example` does not exist yet, create `.env` manually:

```sh
FUTU_TRADE_PASSWORD=replace-me
```

Keep `.env` out of Git.

## 4. Smoke Test

Check Futu OpenD before running Finviz or strategy logic:

```sh
uv run python main.py \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --check-futu
```

Run the screener only:

```sh
uv run python main.py --limit 10
```

Dry-run against OpenD:

```sh
uv run python main.py \
  --limit 10 \
  --cash 100000 \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --plan
```

Simulated order test:

```sh
uv run python main.py \
  --cash 100000 \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --execute
```

Real market orders:

```sh
set -a
. ./.env
set +a

uv run python main.py \
  --cash 100000 \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --auto \
  --real \
  --cancel-open-orders \
  --max-gross-exposure 0.8 \
  --max-position-weight 0.12 \
  --rebalance-threshold 0.03
```

Orders are market orders by default. Add `--order-type NORMAL` only if you want
normal limit orders using the planned price.

## 5. Troubleshooting OpenD

If the app prints `RemoteClose`, `Disconnect context`, or cannot query account
info, check OpenD before changing strategy code:

```sh
docker ps --filter name=futu-opend-docker
docker logs --tail 100 futu-opend-docker
```

Confirm the host can reach OpenD:

```sh
nc -vz 127.0.0.1 11111
uv run python main.py --check-futu
```

Common causes:

- OpenD container is not running.
- OpenD has not finished login.
- SMS verification is waiting on telnet port `22222`.
- Picture CAPTCHA is waiting in the container.
- `FUTU_ACCOUNT_ID` or `FUTU_ACCOUNT_PWD_MD5` is wrong.
- The OpenD container was started with Docker bridge networking instead of
  `--network host`.
- `FUTU_OPEND_IP` is not `127.0.0.1` when using host networking.

If SMS is required:

```sh
echo "input_phone_verify_code -code=123456" | telnet localhost 22222
```

If CAPTCHA is required:

```sh
docker cp futu-opend-docker:/home/futu/.com.futunn.FutuOpenD/F3CNN/PicVerifyCode.png ./PicVerifyCode.png
echo "input_pic_verify_code -code=abcd" | telnet localhost 22222
```

## 6. Stop Switch

Create this file to stop order execution:

```sh
touch STOP_TRADING
```

Remove it to resume:

```sh
rm STOP_TRADING
```

`trade_journal.json` stores submitted and cancelled order records. Back it up
before redeploying or replacing the server.

## 7. Optional Daily Timer

Create a runner script:

```sh
mkdir -p ~/.local/bin
vim ~/.local/bin/algo-trading-run
```

Script content:

```sh
#!/usr/bin/env sh
set -eu

cd "$HOME/projects/algo-trading"
set -a
. ./.env
set +a

uv run python main.py \
  --cash 100000 \
  --futu-host 127.0.0.1 \
  --futu-port 11111 \
  --auto \
  --real \
  --cancel-open-orders \
  --max-gross-exposure 0.8 \
  --max-position-weight 0.12 \
  --rebalance-threshold 0.03
```

Make it executable:

```sh
chmod +x ~/.local/bin/algo-trading-run
```

Create the systemd user service:

```sh
mkdir -p ~/.config/systemd/user
vim ~/.config/systemd/user/algo-trading.service
```

```ini
[Unit]
Description=Algo Trading Daily Run
After=default.target

[Service]
Type=oneshot
ExecStart=%h/.local/bin/algo-trading-run
WorkingDirectory=%h/projects/algo-trading
```

Create the timer:

```sh
vim ~/.config/systemd/user/algo-trading.timer
```

```ini
[Unit]
Description=Run Algo Trading Daily

[Timer]
OnCalendar=Mon..Fri 22:35:00
Persistent=true
Unit=algo-trading.service

[Install]
WantedBy=timers.target
```

Enable it:

```sh
systemctl --user daemon-reload
systemctl --user enable --now algo-trading.timer
loginctl enable-linger "$USER"
```

Check timer and logs:

```sh
systemctl --user list-timers algo-trading.timer
journalctl --user -u algo-trading.service -f
```

The timer example uses server local time. Adjust `OnCalendar` to match your
market-open workflow and server timezone.

## 8. Update Deployment

```sh
cd ~/projects/algo-trading
git pull
uv sync
uv run python -m compileall main.py algo_trading
systemctl --user restart algo-trading.timer
```

If OpenD needs an image update:

```sh
docker pull ghcr.io/manhinhang/futu-opend-docker:ubuntu-stable
docker stop futu-opend-docker
docker rm futu-opend-docker
```

Then start it again using the `docker run` command above.

To force a fresh OpenD login, remove the data volume after stopping the
container:

```sh
docker volume rm futu-opend-data
```
