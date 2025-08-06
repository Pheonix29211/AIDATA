import os
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

# Login to TradingView using Render secrets
tv = TvDatafeed(
    username=os.getenv("TV_USERNAME"),
    password=os.getenv("TV_PASSWORD")
)

def fetch_mnq_data(symbol="MNQU5", exchange="CME_MINI", interval=Interval.in_5_minute, n_bars=100):
    try:
        data = tv.get_hist(symbol=symbol, exchange=exchange, interval=interval, n_bars=n_bars)
        latest = data.iloc[-1]
        close = latest['close']
        vwap = data['close'].rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + data['close'].pct_change().rolling(14).mean().iloc[-1]))

        signal = ""
        if close > vwap and rsi < 70:
            signal = "🟢 Long Setup (Close above VWAP, RSI < 70)"
        elif close < vwap and rsi > 30:
            signal = "🔴 Short Setup (Close below VWAP, RSI > 30)"
        else:
            signal = "🟡 No Clear Signal"

        return f"📊 MNQU5 Signal:\nPrice: {close:.2f}\nVWAP: {vwap:.2f}\nRSI: {rsi:.2f}\n\n{signal}"
    except Exception as e:
        return f"❌ Error generating signal: {str(e)}"

def scan_market_and_send_alerts(update, context):
    result = fetch_mnq_data()
    context.bot.send_message(chat_id=update.effective_chat.id, text=result)

def get_bot_status(update, context):
    status = (
        "📌 Strategy:\n"
        "• 5m Timeframe\n"
        "• VWAP + RSI\n"
        "• MNQU5 futures\n"
        "• News support coming soon\n"
        "• SL: 15 pts | TP: 3x\n"
    )
    context.bot.send_message(chat_id=update.effective_chat.id, text=status)

def get_trade_logs(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="📜 Trade logs not yet implemented.")

def get_trade_results(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="📈 Trade results tracking coming soon.")

def check_tvdata_connection(update, context):
    try:
        tv.get_hist(symbol="MNQU5", exchange="CME_MINI", interval=Interval.in_5_minute, n_bars=5)
        context.bot.send_message(chat_id=update.effective_chat.id, text="✅ TradingView connection OK!")
    except Exception as e:
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ TradingView connection failed: {str(e)}")
