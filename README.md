# AmneziaWG Telegram bot

An admin-only Telegram bot that runs `manage_amneziawg.sh add <client_name>` and sends the generated QR image and `vpn://` URI to the admin who requested the client. The bot uses long polling and logs received Telegram updates with their user and chat IDs to the systemd journal.

## Configuration

Create a bot with BotFather and get the numeric Telegram user IDs of your admins. Copy `.env.example` to `.env` and set `BOT_TOKEN` and `ADMIN_TG_ID`. Keep `.env` readable only by the service operator (`chmod 600 .env`). All runtime settings are in `.env`:

| Setting | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token |
| `ADMIN_TG_ID` | Comma-separated admin user IDs, for example `123456789,987654321` |
| `MANAGE_SCRIPT` | Absolute path to the production management script |
| `CLIENT_OUTPUT_DIR` | Directory containing the generated `.png` and `.vpnuri` files |
| `COMMAND_TIMEOUT_SECONDS` | Maximum time for one script call |
| `LOG_LEVEL` | Python log level, normally `INFO` |

The script must be executable and must create `<client_name>.png` and `<client_name>.vpnuri` in `CLIENT_OUTPUT_DIR`. The bot does not need the script during local development; it is used only when `/add` runs. The service example runs as root because the supplied script and output files live under `/root/awg` and client creation changes server configuration.

## Install on the VPN server

The included service expects the project at `/opt/amnz-tg`. Change `WorkingDirectory` and `ExecStart` in `amnz-tg.service` if you use a different location.

```bash
sudo mkdir -p /opt/amnz-tg
sudo cp bot.py requirements.txt .env.example amnz-tg.service /opt/amnz-tg/
cd /opt/amnz-tg
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env
sudo chmod 600 .env
sudoedit .env
sudo install -m 644 amnz-tg.service /etc/systemd/system/amnz-tg.service
sudo systemctl daemon-reload
sudo systemctl enable --now amnz-tg.service
```

Check status and logs with `systemctl status amnz-tg.service` and `journalctl -u amnz-tg.service -f`. An admin must start a private chat with the bot and send `/add serge-mobile2`. The bot sends the PNG as a photo and the URI as text (or a `.vpnuri` document if it is too long for one message) only to that admin.

Client names must contain 1–64 ASCII letters, digits, `_`, or `-` and start with a letter or digit. The bot refuses to run the script if either output file already exists. If creation succeeds but Telegram delivery fails, the files remain on the server; inspect them before retrying with a new name. Requests from other accounts are denied, but their IDs and messages are still logged.
