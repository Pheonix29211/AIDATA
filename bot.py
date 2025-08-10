# bot.py
import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext

from utils import (
    scan_market,        # returns (header, detail) or (text, None)
    diag_data,          # returns string
    run_backtest,       # returns (header, detail)
    get_bot_status,     # returns string
    get_results,        # returns string
    get_trade_logs,     # returns string
    start_background    # starts auto-scan + momentum pings threads
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER = os.getenv("OWNER_CHAT_ID")
HOST  = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost")
PORT  = int(os.getenv("PORT", "10000"))
WEBHOOK_URL = f"https://{HOST}/{TOKEN}"

app = Flask(__name__)
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ---- commands ----
def start_cmd(update: Update, context: CallbackContext):
    update.message.reply_text("🌀 SpiralBot Online! Use /menu")

def menu_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual scan\n"
        "/forcescan — Force scan now\n"
        "/backtest — 2d backtest (5m)\n"
        "/status — Current logic\n"
        "/results — Win stats\n"
        "/logs — Last trades\n"
        "/diag — Data diag"
    )

def scan_cmd(update: Update, context: CallbackContext):
    head, detail = scan_market()
    update.message.reply_text(head)
    if detail:
        # chunk long texts
        for i in range(0, len(detail), 3500):
            update.message.reply_text(detail[i:i+3500])

def forcescan_cmd(update: Update, context: CallbackContext):
    head, detail = scan_market(force=True)
    update.message.reply_text(head)
    if detail:
        for i in range(0, len(detail), 3500):
            update.message.reply_text(detail[i:i+3500])

def backtest_cmd(update: Update, context: CallbackContext):
    head, detail = run_backtest(days=2)  # uses your utils
    update.message.reply_text(head)
    if detail:
        for i in range(0, len(detail), 3500):
            update.message.reply_text(detail[i:i+3500])

def status_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(get_bot_status())

def results_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(get_results())

def logs_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(get_trade_logs())

def diag_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(diag_data())

# register handlers
dispatcher.add_handler(CommandHandler("start", start_cmd))
dispatcher.add_handler(CommandHandler("menu", menu_cmd))
dispatcher.add_handler(CommandHandler("scan", scan_cmd))
dispatcher.add_handler(CommandHandler("forcescan", forcescan_cmd))
dispatcher.add_handler(CommandHandler("backtest", backtest_cmd))
dispatcher.add_handler(CommandHandler("status", status_cmd))
dispatcher.add_handler(CommandHandler("results", results_cmd))
dispatcher.add_handler(CommandHandler("logs", logs_cmd))
dispatcher.add_handler(CommandHandler("diag", diag_cmd))

# webhook endpoint
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/", methods=["GET", "HEAD"])
def index():
    return "🌀 SpiralBot Running"

def main():
    # IMPORTANT: start background threads only AFTER bot exists
    start_background(bot)
    bot.set_webhook(WEBHOOK_URL)
    if OWNER:
        bot.send_message(chat_id=OWNER, text=f"✅ Webhook set: {WEBHOOK_URL}")
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
