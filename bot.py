import os
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import CommandHandler, Dispatcher, CallbackContext
from utils import (
    scan_market_and_send_alerts,
    get_trade_logs,
    get_bot_status,
    get_trade_results,
    check_tvdata_connection
)
import threading
import time

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
PORT = int(os.environ.get("PORT", 8443))

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# Command Handlers
def start(update: Update, context: CallbackContext):
    update.message.reply_text("📡 SpiralBot is online! Use /menu to view commands.")

def menu(update: Update, context: CallbackContext):
    update.message.reply_text("""
🌀 SpiralBot Menu:
/scan — Manual Market Scan
/logs — Last 30 Trades
/status — Strategy Info
/results — Win Stats
/check_tv — Test TV Login
""")

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("menu", menu))
dispatcher.add_handler(CommandHandler("scan", scan_market_and_send_alerts))
dispatcher.add_handler(CommandHandler("logs", get_trade_logs))
dispatcher.add_handler(CommandHandler("status", get_bot_status))
dispatcher.add_handler(CommandHandler("results", get_trade_results))
dispatcher.add_handler(CommandHandler("check_tv", check_tvdata_connection))

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route('/')
def index():
    return "🌀 SpiralBot Running"

# Auto scanner
def auto_scan():
    while True:
        try:
            scan_market_and_send_alerts()
        except Exception as e:
            print("Scan failed:", e)
        time.sleep(60)

if __name__ == '__main__':
    bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook set:", WEBHOOK_URL)
    threading.Thread(target=auto_scan).start()
    app.run(host="0.0.0.0", port=PORT)
