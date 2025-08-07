import os
import time
from flask import Flask, request
from telegram import Bot
from telegram.ext import Dispatcher, CommandHandler
from utils import (
    scan_market,
    get_recent_trades,
    get_results,
    get_status,
    monitor_open_trade
)

TOKEN = os.getenv("BOT_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
app = Flask(__name__)
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, workers=0)

# === Commands ===
def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="🌀 SpiralBot active.")

def scan(update, context):
    signal = scan_market()
    context.bot.send_message(chat_id=update.effective_chat.id, text=signal)

def logs(update, context):
    trades = get_recent_trades()
    context.bot.send_message(chat_id=update.effective_chat.id, text=trades)

def results(update, context):
    res = get_results()
    context.bot.send_message(chat_id=update.effective_chat.id, text=res)

def status(update, context):
    logic = get_status()
    context.bot.send_message(chat_id=update.effective_chat.id, text=logic)

def menu(update, context):
    menu_text = (
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual scan\n"
        "/logs — Last 30 trades\n"
        "/status — Current logic\n"
        "/results — Win stats\n"
    )
    context.bot.send_message(chat_id=update.effective_chat.id, text=menu_text)

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("scan", scan))
dispatcher.add_handler(CommandHandler("logs", logs))
dispatcher.add_handler(CommandHandler("results", results))
dispatcher.add_handler(CommandHandler("status", status))
dispatcher.add_handler(CommandHandler("menu", menu))

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json(force=True)
    dispatcher.process_update(update)
    return "OK"

@app.route("/")
def index():
    return "Bot is live."

# === Auto Scanner ===
def auto_scan():
    while True:
        signal = scan_market()
        if signal:
            bot.send_message(chat_id=OWNER_CHAT_ID, text=signal)
            time.sleep(60)  # Wait a bit after signal before monitoring
            monitor_open_trade(bot, OWNER_CHAT_ID)
        time.sleep(300)  # Scan every 5 mins

if name == "__main__":
    from threading import Thread
    Thread(target=auto_scan).start()
    app.run(host="0.0.0.0", port=10000)