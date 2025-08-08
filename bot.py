import os
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

# --- Config ---
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/{TOKEN}"
PORT = int(os.environ.get("PORT", 10000))

bot = Bot(token=TOKEN)
app = Flask(__name__)
dispatcher = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# ---------- Commands ----------
def start_cmd(update: Update, _: CallbackContext):
    update.message.reply_text(
        "🌀 SpiralBot Online\n\n"
        "/scan — Manual scan\n"
        "/forcescan — Force scan now\n"
        "/logs — Last 30 trades\n"
        "/results — Win stats\n"
        "/backtest — Stream 2-day backtest\n"
        "/check_data — Verify data source\n"
        "/diag — Last API responses"
    )

def scan_cmd(update: Update, _: CallbackContext):
    title, body = scan_market()
    update.message.reply_text(f"{title or 'ℹ️'}\n{body}")

def forcescan_cmd(update: Update, _: CallbackContext):
    title, body = scan_market()
    update.message.reply_text(f"{title or 'ℹ️'}\n{body}")

def logs_cmd(update: Update, _: CallbackContext):
    logs = get_trade_logs(30)
    if not logs:
        update.message.reply_text("No trades logged yet.")
        return
    chunks = []
    for t in logs[-30:]:
        line = (
            f"{t.get('time','')} | {t.get('signal','').upper()} | "
            f"Entry {round(t.get('entry',0))} | SL {round(t.get('sl',0))} | "
            f"TP1 {round(t.get('tp1',0))}→TP2 {round(t.get('tp2',0))} | "
            f"RSI {round(t.get('rsi',0),1)} | src {t.get('source','')}"
        )
        chunks.append(line)
    update.message.reply_text("🧾 Recent Trades:\n" + "\n".join(chunks[-30:]))

def results_cmd(update: Update, _: CallbackContext):
    total, wins, win_rate, avg_score = get_results()
    update.message.reply_text(
        f"📈 Results:\n"
        f"Trades: {total}\nWins: {wins}\nWin rate: {win_rate}%\nAvg score: {avg_score}"
    )

def backtest_cmd(update: Update, _: CallbackContext):
    lines = run_backtest_stream(days=2)
    msg = "\n".join(lines)
    update.message.reply_text(msg if msg else "(Backtest finished.)")

def check_data_cmd(update: Update, _: CallbackContext):
    update.message.reply_text(check_data_source())

def diag_cmd(update: Update, _: CallbackContext):
    update.message.reply_text("🔧 Diag:\n" + quick_diag())

# Register
dispatcher.add_handler(CommandHandler("start", start_cmd))
dispatcher.add_handler(CommandHandler("scan", scan_cmd))
dispatcher.add_handler(CommandHandler("forcescan", forcescan_cmd))
dispatcher.add_handler(CommandHandler("logs", logs_cmd))
dispatcher.add_handler(CommandHandler("results", results_cmd))
dispatcher.add_handler(CommandHandler("backtest", backtest_cmd))
dispatcher.add_handler(CommandHandler("check_data", check_data_cmd))
dispatcher.add_handler(CommandHandler("diag", diag_cmd))

# ---------- Auto Scan ----------
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

# Webhook endpoints
@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return "ok"

@app.route("/")
def index():
    return "🌀 SpiralBot Running"

if __name__ == "__main__":
    # Start auto-scan thread if enabled
    if os.getenv("AUTO_SCAN", "0") == "1":
        threading.Thread(target=auto_scan_loop, daemon=True).start()

    bot.set_webhook(WEBHOOK_URL)
    print("✅ Webhook set:", WEBHOOK_URL)
    app.run(host="0.0.0.0", port=PORT)
