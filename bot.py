import os
import threading
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from utils import (
    scan_market_and_send_alerts,
    get_trade_logs,
    get_bot_status,
    get_trade_results,
    check_tvdata_connection,
    auto_scan
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
PORT = int(os.environ.get("PORT", 8443))

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# Commands
def start(update: Update, context: CallbackContext):
    update.message.reply_text("📡 SpiralBot US100 Online! Use /menu for commands.")

def menu(update: Update, context: CallbackContext):
    update.message.reply_text("""
🌀 SpiralBot Menu:
/scan — Manual scan
/logs — Last 30 trades
/status — Current logic
/results — Win stats
/check_tv — Verify data source
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

if __name__ == '__main__':
    bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook set:", WEBHOOK_URL)
    # Start background auto scan
    threading.Thread(target=auto_scan, args=(bot,), daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
