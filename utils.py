import os
import numpy as np
from tvDatafeed import TvDatafeed, Interval

tv = TvDatafeed(
    username=os.getenv("TV_USERNAME"),
    password=os.getenv("TV_PASSWORD")
)

trade_logs = []

def scan_market_and_send_alerts(update, context):
    try:
        data = tv.get_hist(symbol="MNQ1!", exchange="CME_MINI", interval=Interval.in_1_minute, n_bars=100)
    except Exception as e:
        update.message.reply_text(f"❌ TradingView connection failed: {str(e)}")
        return

    latest = data.iloc[-1]
    close = latest['close']
    vwap = data['close'].rolling(14).mean().iloc[-1]
    rsi = 100 - (100 / (1 + data['close'].pct_change().rolling(14).mean().iloc[-1]))

    lower_wick = latest['low']
    upper_wick = latest['high']
    body = abs(latest['open'] - latest['close'])

    momentum = "🔥 Hold momentum" if close > vwap and rsi > 55 else "⚠️ Caution"

    direction = ""
    if close > vwap and rsi < 70:
        direction = "🟢 Long Setup"
    elif close < vwap and rsi > 30:
        direction = "🔴 Short Setup"
    else:
        direction = "🟡 Neutral"

    signal = f"""
📊 *MNQU5 Signal*:
Price: `{close:.2f}`
VWAP: `{vwap:.2f}`
RSI: `{rsi:.2f}`

{direction}
{momentum}
"""

    context.bot.send_message(chat_id=update.effective_chat.id, text=signal, parse_mode='Markdown')
    trade_logs.append(signal)
    if len(trade_logs) > 30:
        trade_logs.pop(0)

def get_trade_logs(update, context):
    if not trade_logs:
        update.message.reply_text("No trades logged yet.")
    else:
        update.message.reply_text("\n\n".join(trade_logs[-10:]))

def get_bot_status(update, context):
    update.message.reply_text("✅ Bot is running.\n1-min auto scan enabled.\nPremium TV login in use.")

def get_trade_results(update, context):
    wins = sum(1 for log in trade_logs if "Long" in log or "Short" in log)
    update.message.reply_text(f"📈 Total trades: {len(trade_logs)}\n📊 Trade setups detected: {wins}")

def check_tvdata_connection(update, context):
    try:
        tv.get_hist(symbol="MNQ1!", exchange="CME_MINI", interval=Interval.in_1_minute, n_bars=1)
        update.message.reply_text("✅ TradingView data feed working.")
    except Exception as e:
        update.message.reply_text(f"❌ TV connection failed: {str(e)}")
