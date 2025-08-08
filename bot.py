import os
import time
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
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("SpiralBot")

# -------------------- Command handlers -------------------- #

def start(update, context):
    update.message.reply_text("🌀 SpiralBot Online. Use /menu to see commands.")

def menu(update, context):
    update.message.reply_text(
        "🌀 SpiralBot Menu:\n"
        "/scan — Manual scan\n"
        "/forcescan — Instant scan test\n"
        "/logs — Last 30 trades\n"
        "/results — Win stats\n"
        "/status — Current logic\n"
        "/check_data — Verify data source\n"
        "/backtest — 2-day replay (streamed)\n"
    )

def scan_command(update, context):
    # Backward-compatible handling: utils.scan_market() returns (signal_text_or_None, msg_or_None)
    a, b = scan_market()
    text = a if a else b if b else "No signal."
    update.message.reply_text(text)

def forcescan_command(update, context):
    update.message.reply_text("⏱️ Forcing a fresh scan…")
    a, b = scan_market()
    text = a if a else b if b else "No signal."
    update.message.reply_text(f"📡 Force Scan Result:\n{text}")

def logs_command(update, context):
    logs = get_trade_logs()
    if not logs:
        update.message.reply_text("No trades yet.")
        return
    lines = []
    for t in reversed(logs):
        lines.append(
            f"{t.get('time','-')} | {t.get('direction','-')} @ {round(t.get('entry',0))} | "
            f"SL {round(t.get('sl',0))} TP {round(t.get('tp',0))} | "
            f"Score {t.get('score','-')} | {t.get('outcome','-')}"
        )
    msg = "📊 Last trades:\n" + "\n".join(lines[:30])
    update.message.reply_text(msg[:4000])

def results_command(update, context):
    total, wins, winrate, avg_score = get_results()
    update.message.reply_text(
        f"📈 Performance Stats\n"
        f"Total trades: {total}\n"
        f"Wins: {wins}\n"
        f"Win rate: {winrate}%\n"
        f"Avg score: {avg_score}"
    )

def status_command(update, context):
    update.message.reply_text(
        "📊 Current Logic:\n"
        "- BTCUSDT (Bybit primary, MEXC fallback)\n"
        "- VWAP + EMA (1m/5m), RSI, Engulfing\n"
        "- $300 SL, $600–$1500 TP\n"
        "- Learning log enabled\n"
    )

def check_data_command(update, context):
    update.message.reply_text(check_data_source())

def backtest_command(update, context):
    chat_id = update.effective_chat.id
    update.message.reply_text("🧪 Starting 2-day backtest… streaming entries & outcomes.")

    def _runner():
        # utils.run_backtest_stream currently returns a list of lines OR streams internally.
        try:
            lines = run_backtest_stream(days=2)
            # If it returned a list, stream them; if it already streamed, lines may be None
            if isinstance(lines, list) and lines:
                for line in lines:
                    try:
                        context.bot.send_message(chat_id=chat_id, text=line)
                        time.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"send fail: {e}")
        except Exception as e:
            context.bot.send_message(chat_id=chat_id, text=f"❌ Backtest error: {e}")

    threading.Thread(target=_runner, daemon=True).start()

# -------------------- Bootstrap (webhook) -------------------- #

def main():
    TOKEN = os.environ.get("TOKEN")
    HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    PORT = int(os.environ.get("PORT", "8443"))

    if not TOKEN:
        print("❌ TOKEN env var missing.")
        return
    if not HOSTNAME:
        print("❌ RENDER_EXTERNAL_HOSTNAME env var missing.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Register commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CommandHandler("scan", scan_command))
    dp.add_handler(CommandHandler("forcescan", forcescan_command))
    dp.add_handler(CommandHandler("logs", logs_command))
    dp.add_handler(CommandHandler("results", results_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CommandHandler("check_data", check_data_command))
    dp.add_handler(CommandHandler("backtest", backtest_command))

    # Webhook
    webhook_path = TOKEN
    webhook_url = f"https://{HOSTNAME}/{webhook_path}"
    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=webhook_url,
    )
    print(f"✅ Webhook set: {webhook_url}")
    updater.idle()

if __name__ == "__main__":
    main()
