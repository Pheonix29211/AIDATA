import os
import logging
import threading
from telegram.ext import Updater, CommandHandler
from utils import (
    scan_market,
    get_trade_logs,
    get_results,
    check_data_source,
    run_backtest_stream,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Command handlers ---

def start(update, context):
    update.message.reply_text("🌀 SpiralBot Activated.\nUse /menu to view commands.")

def menu(update, context):
    commands = (
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual scan\n"
        "/logs — Last 30 trades\n"
        "/results — Win stats\n"
        "/status — Current logic\n"
        "/check_data — Verify data source\n"
        "/backtest — 2-day streamed replay (5m pace)\n"
    )
    update.message.reply_text(commands)

def scan_command(update, context):
    trade, text = scan_market()
    update.message.reply_text(text)

def logs_command(update, context):
    logs = get_trade_logs()
    if not logs:
        update.message.reply_text("No trades yet.")
        return
    recent = logs[-30:]
    formatted = "\n".join([
        f"{t.get('type','-').upper()} @ {round(t.get('price',0))} | "
        f"Score: {t.get('score','-')} | Outcome: {t.get('outcome','-')}"
        for t in reversed(recent)
    ])
    update.message.reply_text(f"📊 Last {len(recent)} trades:\n{formatted}")

def results_command(update, context):
    winrate, wins, losses, avg_score = get_results()
    update.message.reply_text(
        f"📈 Performance Stats:\n"
        f"Wins: {wins}\n"
        f"Losses: {losses}\n"
        f"Win Rate: {winrate}%\n"
        f"Avg Score: {avg_score}"
    )

def status_command(update, context):
    update.message.reply_text(
        "📊 Current Logic:\n"
        "- BTCUSDT on Bybit (fallback: MEXC)\n"
        "- VWAP/EMA cross (1m & 5m)\n"
        "- RSI + Engulfing pattern\n"
        "- $300 SL, $600–$1500 TP\n"
        "- Momentum pings every 1m\n"
        "- No duplicate trades\n"
        "- Learning log enabled"
    )

def check_data(update, context):
    source = check_data_source()
    update.message.reply_text(source)

def backtest_command(update, context):
    chat_id = update.effective_chat.id
    update.message.reply_text(
        "🧪 Starting 2-day backtest at real-time pace (5m per candle)…\n"
        "You’ll receive entries and TP/SL notifications as they ‘replay’."
    )
    def _runner():
        run_backtest_stream(
            notify=lambda msg: context.bot.send_message(chat_id=chat_id, text=msg),
            bars=576,  # ~48h (5m candles)
        )
    threading.Thread(target=_runner, daemon=True).start()

# --- Main / webhook ---

def main():
    TOKEN = os.environ.get("TOKEN")
    if not TOKEN:
        print("❌ TOKEN not found in environment variables.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CommandHandler("scan", scan_command))
    dp.add_handler(CommandHandler("logs", logs_command))
    dp.add_handler(CommandHandler("results", results_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CommandHandler("check_data", check_data))
    dp.add_handler(CommandHandler("backtest", backtest_command))

    PORT = int(os.environ.get("PORT", 8443))
    HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if not HOSTNAME:
        print("❌ HOSTNAME missing. Set RENDER_EXTERNAL_HOSTNAME in env vars.")
        return

    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{HOSTNAME}/{TOKEN}",
    )
    updater.idle()

if __name__ == "__main__":
    main()
