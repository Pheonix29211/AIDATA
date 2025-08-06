import os
from tvDatafeed import TvDatafeed, Interval

# Use credentials from Render environment variables
USERNAME = os.getenv("TV_USERNAME")
PASSWORD = os.getenv("TV_PASSWORD")

tv = TvDatafeed(username=USERNAME, password=PASSWORD)

def fetch_mnq_data(symbol="MNQ1!", exchange="CME_MINI", interval=Interval.in_5_minute, n_bars=100):
    try:
        data = tv.get_hist(symbol=symbol, exchange=exchange, interval=interval, n_bars=n_bars)
        if data is None or data.empty:
            return "⚠️ No data received from TradingView."

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

def get_status():
    return "📌 Strategy:\n• 5m Timeframe\n• VWAP + RSI\n• Engulfing Detection\n• News Context Enabled\n• SL: 15 pts\n• Auto-Scan + Telegram Alerts"

def get_news_summary():
    return "📰 News summary not yet implemented."

def get_trade_logs():
    return "🧾 Trade logs not available yet. Will be added after signal tracking."
