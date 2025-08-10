# bot.py
import os
import logging
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext

# --- Logging ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("spiralbot")

# --- Utils (required) ---
from utils import scan_market, diag_data, run_backtest, get_bot_status, get_results, get_trade_logs, get_ai_status

# --- Config from env ---
TOKEN = os.getenv("BOT_TOKEN")  # Telegram bot token
if not TOKEN:
    raise SystemExit("❌ BOT_TOKEN is missing in environment.")

HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")  # e.g. myapp.onrender.com
PORT = int(os.environ.get("PORT", 10000))         # Render provides PORT
WEBHOOK_URL = f"https://{HOSTNAME}/{TOKEN}" if HOSTNAME else None

# --- Telegram objects ---
bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# --- Helpers ---
def send_long(chat_id: int, text: str):
    """Split long messages to fit Telegram limits."""
    if not text:
        return
    MAX = 3800
    for i in range(0, len(text), MAX):
        bot.send_message(chat_id=chat_id, text=text[i:i+MAX])

# --- Commands ---
def start(update: Update, context: CallbackContext):
    update.message.reply_text("🌀 SpiralBot Online! Use /menu to see options.")

def menu(update: Update, context: CallbackContext):
    txt = (
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual scan\n"
        "/forcescan — Force scan now\n"
        "/diag — Data source diagnostics\n"
        "/status — Current logic\n"
        "/results — Win stats\n"
        "/logs — Last trades\n"
        "/backtest — 2-day backtest (or /backtest 3)\n"
    )
    update.message.reply_text(txt)

def scan_command(update: Update, context: CallbackContext):
    head, details = scan_market()
    send_long(update.effective_chat.id, f"{head}\n{details}")

def forcescan_command(update: Update, context: CallbackContext):
    head, details = scan_market()
    send_long(update.effective_chat.id, f"📡 Force Scan Result:\n{head}\n{details}")

def diag_command(update: Update, context: CallbackContext):
    send_long(update.effective_chat.id, diag_data())

def status_command(update: Update, context: CallbackContext):
    base = get_bot_status()
    ai   = get_ai_status()
    send_long(update.effective_chat.id, base + "\n" + ai)

def results_command(update: Update, context: CallbackContext):
    send_long(update.effective_chat.id, get_results())

def logs_command(update: Update, context: CallbackContext):
    send_long(update.effective_chat.id, get_trade_logs())

def backtest_command(update: Update, context: CallbackContext):
    # /backtest or /backtest N
    days = 2
    try:
        if context.args and len(context.args) >= 1:
            days = max(1, min(7, int(context.args[0])))
    except Exception:
        pass
    head, details = run_backtest(days=days)
    send_long(update.effective_chat.id, f"{head}\n{details}")

# --- Register handlers ---
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("menu", menu))
dispatcher.add_handler(CommandHandler("scan", scan_command))
dispatcher.add_handler(CommandHandler("forcescan", forcescan_command))
dispatcher.add_handler(CommandHandler("diag", diag_command))
dispatcher.add_handler(CommandHandler("status", status_command))
dispatcher.add_handler(CommandHandler("results", results_command))
dispatcher.add_handler(CommandHandler("logs", logs_command))
dispatcher.add_handler(CommandHandler("backtest", backtest_command))

# --- Webhook routes ---
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        dispatcher.process_update(update)
    except Exception as e:
        log.exception("Error processing update: %s", e)
    return "ok"

@app.route('/')
def index():
    return "🌀 SpiralBot Running"

# --- Entrypoint ---
if __name__ == "__main__":
    if WEBHOOK_URL:
        bot.set_webhook(WEBHOOK_URL)
        log.info("✅ Webhook set: %s", WEBHOOK_URL)
    else:
        log.warning("⚠️ RENDER_EXTERNAL_HOSTNAME not set; webhook URL not configured.")
    app.run(host="0.0.0.0", port=PORT)
