import os
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from utils import start_background
start_background(bot)
from utils import (
    scan_market, diag_data, run_backtest, get_bot_status,
    get_results, get_trade_logs, start_background, get_ai_status
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
WEBHOOK_URL = f"https://{HOST}/{TOKEN}"
PORT = int(os.getenv("PORT", "10000"))

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ------------- helpers -------------
def _send_long(chat_id, text):
    # Telegram hard limit ~4096 chars
    chunk = 3800
    if len(text) <= chunk:
        bot.send_message(chat_id=chat_id, text=text)
    else:
        for i in range(0, len(text), chunk):
            bot.send_message(chat_id=chat_id, text=text[i:i+chunk])

# ------------- commands -------------
def start(update: Update, context: CallbackContext):
    update.message.reply_text("🌀 SpiralBot online. Use /menu")

def menu(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🌀 Menu:\n"
        "/scan — Manual scan\n"
        "/forcescan — Force data + scan now\n"
        "/diag — Data source diagnostics\n"
        "/status — Current logic + open trade\n"
        "/results — Win/SL summary\n"
        "/logs — Last 30 trade events\n"
        "/backtest — 2-day 5m backtest\n"
        "/ai — AI state"
    )

def scan_command(update: Update, context: CallbackContext):
    msg, _ = scan_market()
    update.message.reply_text(msg)

def forcescan_command(update: Update, context: CallbackContext):
    # Same as /scan but we surface errors directly
    msg, _ = scan_market()
    update.message.reply_text(f"📡 Force Scan Result:\n{msg}")

def diag_command(update: Update, context: CallbackContext):
    msg, _ = diag_data()
    update.message.reply_text(msg)

def status_command(update: Update, context: CallbackContext):
    update.message.reply_text(get_bot_status())

def results_command(update: Update, context: CallbackContext):
    update.message.reply_text(get_results())

def logs_command(update: Update, context: CallbackContext):
    _send_long(update.message.chat_id, get_trade_logs(30))

def backtest_command(update, context):
    # allow /backtest or /backtest 2
    try:
        days = int(context.args[0]) if context.args else 2
    except Exception:
        days = 2
    msg = run_backtest(days=days)
    update.message.reply_text(msg[:3900])  # avoid Telegram length errors

dispatcher.add_handler(CommandHandler("backtest", backtest_command))

def ai_command(update: Update, context: CallbackContext):
    update.message.reply_text(get_ai_status())

# register
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("menu", menu))
dispatcher.add_handler(CommandHandler("scan", scan_command))
dispatcher.add_handler(CommandHandler("forcescan", forcescan_command))
dispatcher.add_handler(CommandHandler("diag", diag_command))
dispatcher.add_handler(CommandHandler("status", status_command))
dispatcher.add_handler(CommandHandler("results", results_command))
dispatcher.add_handler(CommandHandler("logs", logs_command))
dispatcher.add_handler(CommandHandler("backtest", backtest_command))
dispatcher.add_handler(CommandHandler("ai", ai_command))

# in bot.py after dispatcher setup:
import threading, time
from utils import momentum_pulse

OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")

def _ping_loop(bot):
    while True:
        try:
            msg = momentum_pulse()
            if msg and OWNER_CHAT_ID:
                bot.send_message(chat_id=OWNER_CHAT_ID, text=msg)
        except Exception:
            pass
        time.sleep(60)

threading.Thread(target=_ping_loop, args=(bot,), daemon=True).start()

# webhook routes
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "🌀 SpiralBot Running"

if __name__ == "__main__":
    # set webhook
    bot.set_webhook(WEBHOOK_URL)
    # start background momentum/manager loop
    try:
        if OWNER_CHAT_ID:
            start_background(bot)
    except Exception:
        pass
    # run flask
    app.run(host="0.0.0.0", port=PORT)