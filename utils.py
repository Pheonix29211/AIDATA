import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

# Global logs
trade_log = []

# RSI calculation
def compute_rsi(data, period=14):
    delta = data['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# Signal logic
def check_for_signal(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]

    rsi = compute_rsi(df).iloc[-1]
    df['rsi'] = compute_rsi(df)

    # Engulfing + VWAP trend
    bullish_engulfing = last['close'] > last['open'] and prev['open'] > prev['close'] and last['close'] > prev['open']
    bearish_engulfing = last['close'] < last['open'] and prev['open'] < prev['close'] and last['close'] < prev['open']
    
    vwap = df['vwap'].iloc[-1]
    bullish_trend = last['close'] > vwap
    bearish_trend = last['close'] < vwap

    signal = None
    confidence = 0

    if bullish_trend and rsi < 30 and bullish_engulfing:
        signal = "BUY"
        confidence += 1

    if bearish_trend and rsi > 70 and bearish_engulfing:
        signal = "SELL"
        confidence += 1

    return signal, rsi, confidence, last['close'], vwap

# Fetch data from TwelveData
def fetch_data():
    api_key = os.getenv("TWELVE_API_KEY")
    url = f"https://api.twelvedata.com/time_series?symbol=US100&interval=5min&outputsize=100&apikey={api_key}&format=JSON"
    try:
        response = requests.get(url)
        data = response.json()
        if "values" not in data:
            return None

        df = pd.DataFrame(data["values"])
        df = df.rename(columns={"datetime": "time"})
        df = df.astype(float, errors='ignore')
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values("time")
        df = df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
        df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3
        return df
    except Exception as e:
        print(f"❌ TV connection failed: {e}")
        return None

# Manual command
def scan_market_and_send_alerts(update=None, context=None, bot=None):
    df = fetch_data()
    if df is None:
        text = "❌ Error: Failed to fetch data"
    else:
        signal, rsi, confidence, price, vwap = check_for_signal(df)
        if signal:
            text = f"📊 US100 Signal:\nPrice: {price:.2f}\nVWAP: {vwap:.2f}\nRSI: {rsi:.2f}\n\n🟢 Signal: {signal}"
            trade_log.append({
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "type": signal,
                "price": price,
                "rsi": rsi,
                "vwap": vwap
            })
        else:
            text = f"📊 US100 Signal:\nPrice: {price:.2f}\nVWAP: {vwap:.2f}\nRSI: {rsi:.2f}\n\n🟡 No Clear Entry"
    
    if update:
        update.message.reply_text(text)
    elif bot:
        chat_id = os.getenv("OWNER_CHAT_ID")
        if chat_id:
            bot.send_message(chat_id=chat_id, text=text)

def get_trade_logs(update, context):
    if not trade_log:
        update.message.reply_text("No trades logged yet.")
        return
    msg = "📝 Last 30 Trades:\n"
    for log in trade_log[-30:]:
        msg += f"{log['time']} | {log['type']} @ {log['price']:.2f} | RSI: {log['rsi']:.2f}\n"
    update.message.reply_text(msg)

def get_bot_status(update, context):
    update.message.reply_text("✅ Strategy uses VWAP + RSI + Engulfing + Momentum on US100 (5m). Auto-scanning every 5 mins.")

def get_trade_results(update, context):
    if not trade_log:
        update.message.reply_text("No trades logged yet.")
        return
    buys = [t for t in trade_log if t['type'] == "BUY"]
    sells = [t for t in trade_log if t['type'] == "SELL"]
    update.message.reply_text(f"📈 Total Trades: {len(trade_log)}\n🟢 BUYs: {len(buys)}\n🔴 SELLs: {len(sells)}")

def check_tvdata_connection(update, context):
    df = fetch_data()
    if df is not None:
        update.message.reply_text("✅ TradingView (via TwelveData) connection successful.")
    else:
        update.message.reply_text("❌ TV connection failed.")

# Auto scan every 5 minutes
def auto_scan(bot):
    while True:
        scan_market_and_send_alerts(bot=bot)
        time.sleep(300)
