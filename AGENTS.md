# Repository notes for agents

- This is a small Python Telegram bot; keep dependencies and behavior simple.
- The production script `/root/awg/manage_amneziawg.sh` is absent in this workspace. Never assume it can be executed locally. Mock it for local verification.
- Keep all runtime settings in `.env` and secrets out of version control. Update `.env.example` and `README.md` when settings change.
- Only configured admins may create clients. Send generated VPN credentials to every configured admin in a private chat.
- Log every received update with the Telegram user ID. Do not log generated VPN URIs or QR contents.
- The systemd unit is a deployment example for `/opt/amnz-tg` on the VPN server.
