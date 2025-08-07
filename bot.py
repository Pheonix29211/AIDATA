import os
import logging
from telegram.ext import Updater, CommandHandler
from utils import (
    scan_market,
    get_trade_logs,
    get_results_summary,
    get_bot_status,
    check_data_connection,
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_CHAT_ID = int(os.getenv("OWNER_CHAT_ID", "0"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def start(update, context):
    update.message.reply_text("🌀 SpiralBot activated.\nType /menu to see options.")

def menu(update, context):
    update.message.reply_text(
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual signal scan\n"
        "/logs — Last 30 trades\n"
        "/status — Current strategy\n"
        "/results — Win/Loss stats\n"
        "/check_data — Check Bybit/MEXC\n"
    )

def scan(update, context):
    signal = scan_market()
    update.message.reply_text(signal)

def logs(update, context):
    log_data = get_trade_logs()
    update.message.reply_text(log_data)

def status(update, context):
    status = get_bot_status()
    update.message.reply_text(status)

def results(update, context):
    summary = get_results_summary()
    update.message.reply_text(summary)

def check_data(update, context):
    result = check_data_connection()
    update.message.reply_text(result)

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

if __name__ == "__main__":
    main()
