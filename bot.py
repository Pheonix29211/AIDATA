import os
import time
from telegram.ext import Updater, CommandHandler
from utils import (
    scan_market,
    get_trade_logs,
    get_results,
    check_data_source
)

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Bot token missing. Set TOKEN env variable.")

last_trade_time = 0
active_trade = None
TRADE_TIMEOUT = 60 * 30  # 30 mins timeout between trades

def start(update, context):
    update.message.reply_text("🌀 Welcome to SpiralBot BTC\nUse /menu to see available commands.")

def menu(update, context):
    update.message.reply_text(
        """🌀 SpiralBot Menu:
/scan — Manual signal check
/logs — Last 30 trades
/status — Current strategy details
/results — Performance summary
/check_data — Verify data source"""
    )

def scan(update, context):
    global last_trade_time, active_trade

    now = time.time()
    if active_trade and (now - last_trade_time < TRADE_TIMEOUT):
        update.message.reply_text("⏳ Waiting for previous trade to finish...")
        return

    trade, msg = scan_market()
    if trade:
        active_trade = trade
        last_trade_time = now
    update.message.reply_text(msg)

def logs(update, context):
    logs = get_trade_logs()
    if not logs:
        update.message.reply_text("No trades yet.")
        return

    recent = logs[-30:]
    formatted = "\n".join([
        f"{t['type'].upper()} @ {round(t['price'])} | Score: {t['score']} | Outcome: {t.get('outcome', '-')}"
        for t in reversed(recent)
    ])
    update.message.reply_text(f"📊 Last {len(recent)} trades:\n{formatted}")

def results(update, context):
    winrate, wins, losses, avg_score = get_results()
    update.message.reply_text(
        f"""📈 Performance Stats:
Wins: {wins}
Losses: {losses}
Win Rate: {winrate}%
Avg Score: {avg_score}"""
    )

def status(update, context):
    update.message.reply_text(
        """📡 Current Strategy:
• RSI < 30 (long), > 70 (short)
• VWAP trend confirmation
• Engulfing candle required
• Wick% > 20
• Liquidation > $250k
• SL: -$300
• TP: $600–1500+
• 1m + 5m VWAP/EMA momentum pings"""
    )

def check_data(update, context):
    result = check_data_source()
    update.message.reply_text(result)

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CommandHandler("scan", scan))
    dp.add_handler(CommandHandler("logs", logs))
    dp.add_handler(CommandHandler("results", results))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("check_data", check_data))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
