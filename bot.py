# bot.py — Telegram webhook + background pings
import os, threading, time
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext

from utils import (
    scan_market, get_trade_logs, get_bot_status, get_results,
    check_data_source, check_momentum_and_message, clear_open_trade
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.getenv("PORT", "10000"))
WEBHOOK_URL = f"https://{HOST}/{TOKEN}" if HOST and TOKEN else None

bot = Bot(token=TOKEN)
app = Flask(__name__)
dp = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

def _reply(u: Update, text: str):
    try:
        u.message.reply_text(text)
    except Exception:
        if OWNER_CHAT_ID:
            bot.send_message(chat_id=OWNER_CHAT_ID, text=text)

# -------- commands --------
def start(update: Update, ctx: CallbackContext):
    _reply(update, "📡 SpiralBot Online! Use /menu")

def menu(update: Update, ctx: CallbackContext):
    _reply(update, "🌀 Menu:\n/scan\n/forcescan\n/logs\n/results\n/status\n/diag\n/flat")

def scan_command(update: Update, ctx: CallbackContext):
    hdr, body = scan_market()
    if hdr is None:
        _reply(update, body)
    else:
        _reply(update, f"{hdr}\n{body}")

def forcescan_command(update: Update, ctx: CallbackContext):
    scan_command(update, ctx)

def logs_command(update: Update, ctx: CallbackContext):
    _reply(update, get_trade_logs(30))

def results_command(update: Update, ctx: CallbackContext):
    _reply(update, get_results())

def status_command(update: Update, ctx: CallbackContext):
    _reply(update, get_bot_status())

def diag_command(update: Update, ctx: CallbackContext):
    _reply(update, check_data_source())

def flat_command(update: Update, ctx: CallbackContext):
    clear_open_trade()
    _reply(update, "🧹 Cleared current open idea. Pings paused until next signal.")

dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("menu", menu))
dp.add_handler(CommandHandler("scan", scan_command))
dp.add_handler(CommandHandler("forcescan", forcescan_command))
dp.add_handler(CommandHandler("logs", logs_command))
dp.add_handler(CommandHandler("results", results_command))
dp.add_handler(CommandHandler("status", status_command))
dp.add_handler(CommandHandler("diag", diag_command))
dp.add_handler(CommandHandler("flat", flat_command))

# -------- webhook routes --------
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "🌀 SpiralBot Running"

# -------- background momentum ping loop --------
def _ping_loop():
    while True:
        try:
            check_momentum_and_message(bot)
        except Exception:
            pass
        time.sleep(60)

if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.set_webhook(WEBHOOK_URL)
        if OWNER_CHAT_ID:
            bot.send_message(chat_id=OWNER_CHAT_ID, text="✅ Webhook set & bot online")
    threading.Thread(target=_ping_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
