import os
import io
import time
import threading
from flask import Flask, request
from telegram import Bot, Update
from telegram.ext import Dispatcher, CommandHandler, CallbackContext

from utils import (
    scan_market,
    run_backtest_stream,
    get_trade_logs,
    get_results,
    check_data_source,
    quick_diag,
)

# ---------------- Config ----------------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ------------- Helpers ------------------
MAX_TG = 3800  # stay under Telegram ~4096 char limit

def send_text_chunks(chat_id, text):
    """Split a long message into multiple Telegram messages."""
    if len(text) <= MAX_TG:
        bot.send_message(chat_id, text)
        return
    for i in range(0, len(text), MAX_TG):
        bot.send_message(chat_id, text[i:i + MAX_TG])

def send_backtest(chat_id, lines):
    """Send backtest as messages or attach a .txt if too long."""
    msg = "\n".join(lines or [])
    if not msg:
        bot.send_message(chat_id, "(Backtest finished.)")
        return
    if len(msg) <= MAX_TG:
        bot.send_message(chat_id, msg)
    else:
        bio = io.BytesIO(msg.encode("utf-8"))
        bio.name = f"backtest_{int(time.time())}.txt"
        bot.send_document(chat_id, bio, caption="📜 Backtest results (full)")

# ------------- Command Handlers ----------
def start_cmd(update: Update, _: CallbackContext):
    update.message.reply_text(
        "🌀 SpiralBot Online\n\n"
        "/menu — Show commands\n"
        "/scan — Manual scan\n"
        "/forcescan — Force scan now\n"
        "/logs — Last 30 trades\n"
        "/results — Win stats\n"
        "/backtest — Stream 2-day backtest (try `/backtest 3`)\n"
        "/check_data — Verify data source\n"
        "/diag — Last API responses"
    )

def menu_cmd(update: Update, context: CallbackContext):
    start_cmd(update, context)

def scan_cmd(update: Update, _: CallbackContext):
    title, body = scan_market()
    bot.send_message(update.effective_chat.id, f"{title or 'ℹ️'}\n{body}")

def forcescan_cmd(update: Update, _: CallbackContext):
    title, body = scan_market()
    bot.send_message(update.effective_chat.id, f"{title or 'ℹ️'}\n{body}")

def logs_cmd(update: Update, _: CallbackContext):
    logs = get_trade_logs(30)
    if not logs:
        bot.send_message(update.effective_chat.id, "No trades logged yet.")
        return
    lines = []
    for t in logs[-30:]:
        lines.append(
            f"{t.get('time','')} | {t.get('signal','').upper()} | "
            f"Entry {round(t.get('entry',0))} | SL {round(t.get('sl',0))} | "
            f"TP1 {round(t.get('tp1',0))}→TP2 {round(t.get('tp2',0))} | "
            f"RSI {round(t.get('rsi',0),1)} | src {t.get('source','')}"
        )
    send_text_chunks(update.effective_chat.id, "🧾 Recent Trades:\n" + "\n".join(lines))

def results_cmd(update: Update, _: CallbackContext):
    total, wins, win_rate, avg_score = get_results()
    bot.send_message(
        update.effective_chat.id,
        f"📈 Results:\n"
        f"Trades: {total}\nWins: {wins}\nWin rate: {win_rate}%\nAvg score: {avg_score}"
    )

def backtest_cmd(update: Update, _: CallbackContext):
    # optional days argument: /backtest 3
    try:
        parts = update.message.text.strip().split()
        days = int(parts[1]) if len(parts) > 1 else 2
    except Exception:
        days = 2
    lines = run_backtest_stream(days=days)
    send_backtest(update.effective_chat.id, lines)

def check_data_cmd(update: Update, _: CallbackContext):
    bot.send_message(update.effective_chat.id, check_data_source())

def diag_cmd(update: Update, _: CallbackContext):
    bot.send_message(update.effective_chat.id, "🔧 Diag:\n" + quick_diag())

# ---------- Register Handlers -----------
dispatcher.add_handler(CommandHandler("start", start_cmd))
dispatcher.add_handler(CommandHandler("menu", menu_cmd))
dispatcher.add_handler(CommandHandler("help", menu_cmd))
dispatcher.add_handler(CommandHandler("scan", scan_cmd))
dispatcher.add_handler(CommandHandler("forcescan", forcescan_cmd))
dispatcher.add_handler(CommandHandler("logs", logs_cmd))
dispatcher.add_handler(CommandHandler("results", results_cmd))
dispatcher.add_handler(CommandHandler("backtest", backtest_cmd))
dispatcher.add_handler(CommandHandler("check_data", check_data_cmd))
dispatcher.add_handler(CommandHandler("diag", diag_cmd))

# ------------- Auto-scan Thread ----------
def auto_scan_loop():
    interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    chat_id = os.getenv("OWNER_CHAT_ID")
    if not chat_id:
        print("⚠️ AUTO_SCAN enabled but OWNER_CHAT_ID not set.")
        return

    cooldown = int(os.getenv("ALERT_COOLDOWN_SECONDS", "180"))
    last_sent = 0

    while True:
        try:
            title, body = scan_market()
            if title and body:
                now_ts = time.time()
                if now_ts - last_sent > cooldown:
                    bot.send_message(chat_id=chat_id, text=f"{title}\n{body}")
                    last_sent = now_ts
        except Exception as e:
            print("Auto-scan error:", e)
        time.sleep(interval)

# -------------- Webhook ------------------
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "🌀 SpiralBot Running"

# -------------- Main ---------------------
if __name__ == "__main__":
    # Start auto-scan if enabled
    if os.getenv("AUTO_SCAN", "0") == "1":
        threading.Thread(target=auto_scan_loop, daemon=True).start()

    bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook set:", WEBHOOK_URL)
    app.run(host="0.0.0.0", port=PORT)
