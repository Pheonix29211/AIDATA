from tvDatafeed.tvDatafeed import TvDatafeed, Interval
import os

# Authenticate using TradingView credentials from environment variables
tv = TvDatafeed(
    username=os.getenv("TV_USERNAME"),
    password=os.getenv("TV_PASSWORD")
)

def fetch_mnq_data(symbol="MNQ1!", exchange="CME_MINI", interval=Interval.in_5_minutes, n_bars=100):
    try:
        data = tv.get_hist(symbol=symbol, exchange=exchange, interval=interval, n_bars=n_bars)
        if data is None or data.empty:
            return "❌ No data retrieved from TradingView."

        latest = data.iloc[-1]
        close = latest['close']

        # VWAP = simplified rolling average of close prices
        vwap = data['close'].rolling(14).mean().iloc[-1]

        # RSI Calculation
        delta = data['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = -delta.where(delta < 0, 0).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs.iloc[-1]))

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
    return (
        "📌 Strategy:\n"
        "• 5m Timeframe (Interval.in_5_minutes)\n"
        "• VWAP + RSI\n"
        "• Engulfing Detection (coming soon)\n"
        "• News Context Enabled\n"
        "• SL: 15 pts | TP: 45 pts\n"
        "• Auto-Scan + Telegram Alerts"
    )

def get_news_summary():
    # Placeholder for news integration
    return "📰 News summary not yet implemented. Will include macro event bias soon."
