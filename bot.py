import os
import logging
from telegram.ext import Updater, CommandHandler
from utils import (
    scan_market,
    get_trade_logs,
    get_results,
    check_data_source
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start(update, context):
    update.message.reply_text("🌀 SpiralBot Activated.\nUse /menu to view commands.")

def menu(update, context):
    commands = """
🌀 SpiralBot Menu:
/scan — Manual scan
/logs — Last 30 trades
/status — Current logic
/results — Win stats
/check_data — Verify data source
"""
    update.message.reply_text(commands)

def scan_command(update, context):
    result = scan_market()
    update.message.reply_text(result)

def logs_command(update, context):
    logs = get_trade_logs()
    update.message.reply_text(logs)

def results_command(update, context):
    summary = get_results()
    update.message.reply_text(summary)

def status_command(update, context):
    message = "📊 Current Logic:\n- BTCUSDT on Bybit (fallback: MEXC)\n- VWAP/EMA cross (1m & 5m)\n- RSI + Engulfing pattern\n- $300 SL, $600–$1500 TP\n- Momentum pings every 1m\n- No duplicate trades\n- Learning log enabled"
    update.message.reply_text(message)

def check_data(update, context):
    source = check_data_source()
    update.message.reply_text(source)

def main():
    TOKEN = os.environ.get("TOKEN")
    if not TOKEN:
        print("❌ TOKEN not found in environment variables.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CommandHandler("scan", scan_command))
    dp.add_handler(CommandHandler("logs", logs_command))
    dp.add_handler(CommandHandler("results", results_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CommandHandler("check_data", check_data))

    PORT = int(os.environ.get("PORT", 8443))
    HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if not HOSTNAME:
        print("❌ HOSTNAME missing. Set RENDER_EXTERNAL_HOSTNAME in env vars.")
        return

    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{HOSTNAME}/{TOKEN}",
    )

    updater.idle()

if __name__ == "__main__":
    main()