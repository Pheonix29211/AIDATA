import os
from telegram import Update, Bot
from telegram.ext import CommandHandler, CallbackContext, Dispatcher
from flask import Flask, request
from utils import (
    scan_market_and_send_alerts,
    get_trade_logs,
    get_bot_status,
    get_trade_results,
    check_tvdata_connection,
    get_news_summary
)

# Telegram & Webhook Config
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
PORT = int(os.environ.get("PORT", 8443))

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# Command Handlers
def start(update: Update, context: CallbackContext):
    update.message.reply_text("📡 SpiralBot Online! Use /menu to see options.")

def menu(update: Update, context: CallbackContext):
    update.message.reply_text("""
🌀 SpiralBot Menu:
/scan — Manual market scan
/logs — Last 30 trades
/status — Current strategy
/results — Win stats
/news — Latest news
/check_tv — Verify TradingView data
""")

def news(update: Update, context: CallbackContext):
    update.message.reply_text(get_news_summary())

# Register Handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("menu", menu))
dispatcher.add_handler(CommandHandler("scan", scan_market_and_send_alerts))
dispatcher.add_handler(CommandHandler("logs", get_trade_logs))
dispatcher.add_handler(CommandHandler("status", get_bot_status))
dispatcher.add_handler(CommandHandler("results", get_trade_results))
dispatcher.add_handler(CommandHandler("check_tv", check_tvdata_connection))
dispatcher.add_handler(CommandHandler("news", news))

# Webhook Route
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
    print("Webhook set:", WEBHOOK_URL)
    app.run(host="0.0.0.0", port=PORT)
