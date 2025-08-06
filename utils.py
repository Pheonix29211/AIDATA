import os
from tvDatafeed import TvDatafeed, Interval

# Authenticate with TradingView using env variables
tv = TvDatafeed(
    username=os.getenv("TV_USERNAME"),
    password=os.getenv("TV_PASSWORD")
)

def fetch_mnq_data(symbol="MNQ1!", exchange="CME_MINI", interval=Interval.in_5_minute, n_bars=100):
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
    alert = fetch_mnq_data()
    context.bot.send_message(chat_id=update.effective_chat.id, text=alert)

def get_bot_status(update, context):
    status = "📌 Strategy:\n• 5m Timeframe\n• VWAP + RSI\n• Engulfing Detection\n• News Context Enabled\n• SL: 15 pts\n• Auto-Scan + Telegram Alerts"
    context.bot.send_message(chat_id=update.effective_chat.id, text=status)

def get_trade_logs(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="🧾 Recent trades will be shown here. (Logging in progress)")

def get_trade_results(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="📈 Results summary under development.")

def check_tvdata_connection(update, context):
    try:
        tv.get_hist("MNQ1!", exchange="CME_MINI", interval=Interval.in_5_minute, n_bars=1)
        context.bot.send_message(chat_id=update.effective_chat.id, text="✅ TradingView connection: SUCCESS")
    except Exception as e:
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ TradingView error: {str(e)}")

def get_news_summary():
    return "📰 News summary not yet implemented. Will include macro event bias soon."
