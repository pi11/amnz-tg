"""Telegram front end for the AmneziaWG client management script."""

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, TypeHandler


LOG = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
CLIENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: tuple[int, ...]
    script: Path
    output_dir: Path
    timeout: int


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env", override=True)
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("BOT_TOKEN is required in .env")
    try:
        timeout = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "120"))
    except ValueError as exc:
        raise ValueError("COMMAND_TIMEOUT_SECONDS must be an integer") from exc
    if timeout <= 0:
        raise ValueError("COMMAND_TIMEOUT_SECONDS must be positive")
    raw_admin_ids = os.getenv("ADMIN_TG_ID", "")
    try:
        admin_ids = tuple(dict.fromkeys(int(value.strip()) for value in raw_admin_ids.split(",")))
    except ValueError as exc:
        raise ValueError("ADMIN_TG_ID must be a comma-separated list of positive integers") from exc
    if any(admin_id <= 0 for admin_id in admin_ids):
        raise ValueError("ADMIN_TG_ID must be a comma-separated list of positive integers")
    script = Path(os.getenv("MANAGE_SCRIPT", "/root/awg/manage_amneziawg.sh"))
    output_dir = Path(os.getenv("CLIENT_OUTPUT_DIR", "/root/awg"))
    if not script.is_absolute() or not output_dir.is_absolute():
        raise ValueError("MANAGE_SCRIPT and CLIENT_OUTPUT_DIR must be absolute paths")
    return Config(token, admin_ids, script, output_dir, timeout)


def create_client(config: Config, name: str) -> tuple[Path, str]:
    """Run the production script and return the QR path and VPN URI."""
    if not CLIENT_NAME.fullmatch(name):
        raise ValueError("Invalid client name")

    qr_path = config.output_dir / f"{name}.png"
    uri_path = config.output_dir / f"{name}.vpnuri"
    if qr_path.exists() or uri_path.exists():
        raise FileExistsError("Client output files already exist")

    result = subprocess.run(
        [str(config.script), "add", name],
        cwd=config.script.parent,
        capture_output=True,
        text=True,
        timeout=config.timeout,
        check=False,
    )
    if result.returncode != 0:
        LOG.error("Client creation failed for %s (exit %d)", name, result.returncode)
        raise RuntimeError(f"Management script exited with status {result.returncode}")
    if not qr_path.is_file() or not uri_path.is_file():
        raise RuntimeError("Management script succeeded but output files are missing")
    uri = uri_path.read_text(encoding="utf-8").strip()
    if not uri.startswith("vpn://"):
        raise RuntimeError("Generated VPN URI is missing or invalid")
    return qr_path, uri


async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None
    message = update.effective_message
    content = (message.text or message.caption) if message else None
    LOG.info("Received update=%s user_id=%s chat_id=%s content=%r", update.update_id, user_id, chat_id, content)


async def check_admin(update: Update, config: Config) -> bool:
    message = update.effective_message
    if message is None:
        return False
    if update.effective_user is None or update.effective_user.id not in config.admin_ids:
        await message.reply_text("Access denied.")
        return False
    if update.effective_chat is None or update.effective_chat.type != "private":
        await message.reply_text("Please use a private chat with the bot.")
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.application.bot_data["config"]
    if await check_admin(update, config):
        await update.effective_message.reply_text("Create a client with /add <client_name>.")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.application.bot_data["config"]
    if not await check_admin(update, config):
        return
    message = update.effective_message
    if len(context.args) != 1 or not CLIENT_NAME.fullmatch(context.args[0]):
        await message.reply_text("Usage: /add <client_name>\nUse 1–64 ASCII letters, digits, _ or -; start with a letter or digit.")
        return

    name = context.args[0]
    await message.reply_text(f"Creating {name}…")
    try:
        qr_path, uri = await asyncio.to_thread(create_client, config, name)
    except FileExistsError:
        await message.reply_text(f"Files for {name} already exist. Choose a new name.")
        return
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        LOG.exception("Could not create client %s", name)
        await message.reply_text("Client creation failed. Check the service log and server files before retrying.")
        return

    LOG.info("Client %s created by Telegram user %s", name, update.effective_user.id)
    try:
        with qr_path.open("rb") as qr_file:
            await context.bot.send_photo(chat_id=update.effective_user.id, photo=qr_file, caption=f"Amnezia client: {name}")
        if len(uri) <= 4000:
            await context.bot.send_message(chat_id=update.effective_user.id, text=uri)
        else:
            uri_path = config.output_dir / f"{name}.vpnuri"
            with uri_path.open("rb") as uri_file:
                await context.bot.send_document(chat_id=update.effective_user.id, document=uri_file, filename=uri_path.name)
    except (OSError, TelegramError):
        LOG.exception("Client %s was created but delivery to admin %s failed", name, update.effective_user.id)
        try:
            await message.reply_text("Client was created, but delivery failed. Retrieve files on the server; do not run /add again.")
        except TelegramError:
            LOG.exception("Could not notify requesting admin about delivery failure")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.application.bot_data["config"]
    if await check_admin(update, config):
        await update.effective_message.reply_text("Use /add <client_name>.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOG.error("Unhandled Telegram update error", exc_info=context.error)


def main() -> None:
    config = load_config()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Application.builder().token(config.token).build()
    app.bot_data["config"] = config
    app.add_handler(TypeHandler(Update, log_update), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(TypeHandler(Update, unknown))
    app.add_error_handler(on_error)
    LOG.info("Bot starting; admin_ids=%s", config.admin_ids)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
