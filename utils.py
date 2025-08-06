import os
from tvDatafeed import TvDatafeed, Interval

# Use TradingView credentials from Render secrets
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

def scan_market_and_send_alerts(bot, chat_id):
    signal = fetch_mnq_data()
    bot.send_message(chat_id=chat_id, text=signal)

def get_status():
    return "📌 Strategy:\n• 5m Timeframe\n• VWAP + RSI\n• Auto-Scan + Telegram Alerts\n• SL: ~10pts (~$38 risk)\n• News context coming soon."

def get_news_summary():
    # Placeholder for future integration
    return "📰 News summary not yet implemented. Will include macro event bias soon."
