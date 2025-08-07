import os
import time
import logging
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, CallbackContext
from utils import (
    scan_market,
    get_trade_logs,
    get_results,
    get_status,
    check_data_source,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")

last_trade_time = 0
scan_interval = 300  # 5 minutes

def restricted(func):
    def wrapped(update: Update, context: CallbackContext, *args, **kwargs):
        if ALLOWED_CHAT_ID and str(update.effective_chat.id) != ALLOWED_CHAT_ID:
            update.message.reply_text("❌ Access denied.")
            return
        return func(update, context, *args, **kwargs)
    return wrapped

@restricted
def scan_command(update: Update, context: CallbackContext):
    result = scan_market()
    update.message.reply_text(result)

@restricted
def logs_command(update: Update, context: CallbackContext):
    logs = get_trade_logs()
    update.message.reply_text(logs)

@restricted
def status_command(update: Update, context: CallbackContext):
    status = get_status()
    update.message.reply_text(status)

@restricted
def results_command(update: Update, context: CallbackContext):
    results = get_results()
    update.message.reply_text(results)

@restricted
def check_data(update: Update, context: CallbackContext):
    result = check_data_source()
    update.message.reply_text(result)

@restricted
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

def auto_scan(context: CallbackContext):
    global last_trade_time
    now = time.time()
    if now - last_trade_time >= scan_interval:
        result = scan_market()
        context.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=result)
        last_trade_time = now

def main():
    if not TOKEN:
        raise ValueError("❌ TOKEN is not set in environment variables.")
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("scan", scan_command))
    dispatcher.add_handler(CommandHandler("logs", logs_command))
    dispatcher.add_handler(CommandHandler("status", status_command))
    dispatcher.add_handler(CommandHandler("results", results_command))
    dispatcher.add_handler(CommandHandler("check_data", check_data))
    dispatcher.add_handler(CommandHandler("menu", menu))

    job_queue = updater.job_queue
    job_queue.run_repeating(auto_scan, interval=60, first=10)  # Auto scan every 1 min

    updater.start_polling()
    updater.idle()

if name == "__main__":
    main()