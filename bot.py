import os
import time
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from utils import (
    scan_market,
    get_trade_logs,
    get_bot_status,
    get_results,
    check_data_source,
)

# Load TOKEN from environment
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("❌ Telegram bot TOKEN not found in environment variables.")

bot = Bot(token=TOKEN)


# === Command Handlers ===
def start(update: Update, context: CallbackContext):
    update.message.reply_text("🌀 SpiralBot started.\nUse /menu to see all commands.")


def menu(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual scan\n"
        "/logs — Last 30 trades\n"
        "/status — Current logic\n"
        "/results — Win stats\n"
        "/check_data — Verify data source\n"
        "/menu — Show this menu"
    )


def scan(update: Update, context: CallbackContext):
    signal = scan_market()
    update.message.reply_text(signal)


def logs(update: Update, context: CallbackContext):
    logs = get_trade_logs()
    update.message.reply_text(logs)


def status(update: Update, context: CallbackContext):
    status_info = get_bot_status()
    update.message.reply_text(status_info)


def results(update: Update, context: CallbackContext):
    result = get_results()
    update.message.reply_text(result)


def check_data(update: Update, context: CallbackContext):
    result = check_data_source()
    update.message.reply_text(result)


# === Main Entry Point ===
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CommandHandler("scan", scan))
    dp.add_handler(CommandHandler("logs", logs))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("results", results))
    dp.add_handler(CommandHandler("check_data", check_data))

    updater.start_polling()
    updater.idle()


if name == "__main__":
    main()
