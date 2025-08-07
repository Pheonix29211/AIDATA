import os
import logging
from telegram.ext import Updater, CommandHandler
from utils import (
    scan_market,
    get_trade_logs,
    get_results,
    get_status
)

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TOKEN")

def start(update, context):
    update.message.reply_text(
        "🌀 *SpiralBot BTC Sniper*\n"
        "/scan — Manual scan\n"
        "/logs — Last 30 trades\n"
        "/status — Current logic\n"
        "/results — Win stats\n"
        "/check_data — Verify data source\n",
        parse_mode="Markdown"
    )

def scan(update, context):
    result = scan_market()
    update.message.reply_text(result, parse_mode="Markdown")

def logs(update, context):
    update.message.reply_text(get_trade_logs(), parse_mode="Markdown")

def results(update, context):
    update.message.reply_text(get_results(), parse_mode="Markdown")

def status(update, context):
    update.message.reply_text(get_status(), parse_mode="Markdown")

def check_data(update, context):
    update.message.reply_text("Checking data source connection...")
    result = scan_market(test_mode=True)
    update.message.reply_text(result, parse_mode="Markdown")

def main():
    if not TOKEN:
        raise ValueError("Bot TOKEN is missing from environment variables.")

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("scan", scan))
    dp.add_handler(CommandHandler("logs", logs))
    dp.add_handler(CommandHandler("results", results))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("check_data", check_data))

    updater.start_polling()
    updater.idle()

if name == "__main__":
    main()