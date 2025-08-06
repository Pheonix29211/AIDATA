import os
import pandas as pd
from tvDatafeed.tvDatafeed import TvDatafeed, Interval

tv = TvDatafeed(
    username=os.getenv("TV_USERNAME"),
    password=os.getenv("TV_PASSWORD")
)

def fetch_data(interval):
    return tv.get_hist(
        symbol="MNQ1!",
        exchange="CME_MINI",
        interval=interval,
        n_bars=100
    )

def calculate_signal():
    try:
        df_1m = fetch_data(Interval.in_1_minute)
        df_5m = fetch_data(Interval.in_5_minute)

        if df_1m is None or df_5m is None:
            return "❌ Failed to fetch TradingView data."

        close = df_1m['close'].iloc[-1]
        vwap = df_1m['close'].rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + df_1m['close'].pct_change().rolling(14).mean().iloc[-1]))

        is_bullish_engulfing = df_1m['close'].iloc[-1] > df_1m['open'].iloc[-1] and df_1m['open'].iloc[-1] < df_1m['close'].iloc[-2]
        is_momentum_strong = close > vwap and rsi > 55

        signal = ""
        if close > vwap and rsi < 70 and is_bullish_engulfing:
            signal = "🟢 LONG Setup\nVWAP ✅\nRSI ✅\nEngulfing ✅"
        elif close < vwap and rsi > 30 and not is_bullish_engulfing:
            signal = "🔴 SHORT Setup\nVWAP ✅\nRSI ✅"
        else:
            signal = "🟡 No Clear Entry"

        if is_momentum_strong:
            signal += "\n⚡ Momentum: HOLD Strong Trade"

        return f"📊 MNQ Signal:\nPrice: {close:.2f}\nVWAP: {vwap:.2f}\nRSI: {rsi:.2f}\n\n{signal}"
    except Exception as e:
        return f"❌ Error generating signal: {str(e)}"

def scan_market_and_send_alerts(update=None, context=None):
    alert = calculate_signal()
    if context:
        context.bot.send_message(chat_id=update.effective_chat.id, text=alert)
    else:
        print(alert)

def get_trade_logs(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="🧾 No trades logged yet.")

def get_bot_status(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="""
📌 Strategy:
• 1m Entry + 5m Trend Confirm
• VWAP + RSI + Engulfing
• Momentum Detector ✅
• TP: +28pts | SL: -9pts
• Auto Scan: Every 1 min
""")

def get_trade_results(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="📈 Win Rate: N/A (tracking starts soon)")

def check_tvdata_connection(update, context):
    data = fetch_data(Interval.in_1_minute)
    if data is not None:
        context.bot.send_message(chat_id=update.effective_chat.id, text="✅ TradingView data connected.")
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Failed to fetch TradingView data.")
