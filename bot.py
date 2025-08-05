import os
import time
import threading
import requests
from telegram.ext import Updater, CommandHandler
from tradovate_api import TradovateClient
from trade_logic import generate_trade_signal, monitor_trade
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USERNAME = os.getenv("TRADOVATE_USERNAME")
PASSWORD = os.getenv("TRADOVATE_PASSWORD")
DEMO = os.getenv("TRADOVATE_DEMO", "true").lower() == "true"

client = TradovateClient(USERNAME, PASSWORD, demo=DEMO)

updater = Updater(TELEGRAM_TOKEN, use_context=True)
dispatcher = updater.dispatcher

active_trades = {}
autoscan_enabled = {"status": False}

def scan(update=None, context=None, auto=False):
    if not auto and update:
        update.message.reply_text("📡 Scanning MNQU5 for setups...")

    signal = generate_trade_signal(client)
    if signal:
        msg = signal['message']
        if update:
            update.message.reply_text(msg)
        else:
            updater.bot.send_message(chat_id=os.getenv("ADMIN_CHAT_ID"), text=msg)

        tid = signal['id']
        active_trades[tid] = signal
        threading.Thread(target=monitor_trade, args=(client, update, signal)).start()
    else:
        if not auto and update:
            update.message.reply_text("⚠️ No valid setups found.")

def pingdata(update, context):
    try:
        price = client.get_last_price("MNQU5")
        update.message.reply_text(f"✅ Tradovate data active\nLast MNQU5 price: {price}")
    except Exception as e:
        update.message.reply_text(f"❌ Error fetching data: {e}")

def autoscan_loop():
    while True:
        if autoscan_enabled["status"]:
            scan(auto=True)
        time.sleep(300)  # every 5 minutes

def autoscan_on(update, context):
    autoscan_enabled["status"] = True
    update.message.reply_text("✅ Auto-scanning enabled. The bot will now scan every 5 minutes.")

def autoscan_off(update, context):
    autoscan_enabled["status"] = False
    update.message.reply_text("🛑 Auto-scanning disabled.")

dispatcher.add_handler(CommandHandler("scan", scan))
dispatcher.add_handler(CommandHandler("pingdata", pingdata))
dispatcher.add_handler(CommandHandler("autoscan_on", autoscan_on))
dispatcher.add_handler(CommandHandler("autoscan_off", autoscan_off))

threading.Thread(target=autoscan_loop, daemon=True).start()

updater.start_polling()
updater.idle()