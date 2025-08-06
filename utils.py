import os
import threading
import time
import pandas as pd
from datetime import datetime
from tvDatafeed.tvDatafeed import TvDatafeed, Interval
import os

tv = TvDatafeed(session=os.getenv("TV_SESSION"))



# --- Memory Trade Log ---
trade_logs = []

def calculate_rsi(data, period=14):
    delta = data['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def detect_engulfing(data):
    prev = data.iloc[-2]
    curr = data.iloc[-1]
    if curr['close'] > curr['open'] and prev['close'] < prev['open']:
        return curr['close'] > prev['open'] and curr['open'] < prev['close']
    if curr['close'] < curr['open'] and prev['close'] > prev['open']:
        return curr['close'] < prev['open'] and curr['open'] > prev['close']
    return False

def fetch_tv_data(interval, bars):
    return tv.get_hist(symbol="MNQ1!", exchange="CME_MINI", interval=interval, n_bars=bars)

def analyze_market():
    try:
        df_1m = fetch_tv_data(Interval.in_1_minute, 100)
        df_5m = fetch_tv_data(Interval.in_5_minute, 100)
        df_1m['rsi'] = calculate_rsi(df_1m)
        vwap_5m = df_5m['close'].rolling(window=14).mean().iloc[-1]

        latest = df_1m.iloc[-1]
        close = latest['close']
        rsi = latest['rsi']
        engulfing = detect_engulfing(df_1m)

        signal = None
        if close > vwap_5m and rsi < 70 and engulfing:
            signal = "🟢 Long Signal"
        elif close < vwap_5m and rsi > 30 and engulfing:
            signal = "🔴 Short Signal"

        if signal:
            log = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "price": close,
                "rsi": round(rsi, 2),
                "vwap": round(vwap_5m, 2),
                "signal": signal,
                "status": "OPEN"
            }
            trade_logs.append(log)
            return f"""
{signal}
Price: {close:.2f}
VWAP: {vwap_5m:.2f}
RSI: {rsi:.2f}
Time: {log['time']}
"""
        else:
            return None
    except Exception as e:
        return f"❌ TV connection failed: {str(e)}"

def scan_market_and_send_alerts(update, context):
    signal = analyze_market()
    if signal:
        update.message.reply_text(signal)
    else:
        update.message.reply_text("🟡 No Signal Right Now")

def get_trade_logs(update, context):
    if not trade_logs:
        update.message.reply_text("📉 No trades logged yet.")
        return
    logs = "\n\n".join([
        f"{log['time']} | {log['signal']} @ {log['price']} | RSI: {log['rsi']} | VWAP: {log['vwap']}"
        for log in trade_logs[-30:]
    ])
    update.message.reply_text(f"📜 Last Trades:\n\n{logs}")

def get_bot_status(update, context):
    update.message.reply_text("""
📌 Strategy Active:
• Entry: 1m chart (Engulfing + RSI)
• Trend: 5m VWAP
• TP: 3x SL (27 pts)
• SL: 9 pts
• Momentum Hold System ✅
• Auto Scan: Every 1 min
""")

def get_trade_results(update, context):
    total = len(trade_logs)
    wins = sum(1 for log in trade_logs if log.get("result") == "WIN")
    losses = sum(1 for log in trade_logs if log.get("result") == "LOSS")
    update.message.reply_text(f"""
📊 Trade Stats:
Total Trades: {total}
Wins: {wins}
Losses: {losses}
Win Rate: {(wins / total * 100):.2f}% 📈
""" if total else "No trades yet.")

def check_tvdata_connection(update, context):
    try:
        df = fetch_tv_data(Interval.in_1_minute, 5)
        if df is not None and not df.empty:
            update.message.reply_text("✅ TradingView connected successfully.")
        else:
            update.message.reply_text("❌ Failed to fetch data.")
    except Exception as e:
        update.message.reply_text(f"❌ Error: {str(e)}")

# --- Auto Scanner ---
def auto_scan(bot):
    while True:
        signal = analyze_market()
        if signal:
            bot.send_message(chat_id=os.getenv("OWNER_CHAT_ID"), text=signal)
        time.sleep(60)

def start_auto_scan(bot):
    thread = threading.Thread(target=auto_scan, args=(bot,))
    thread.daemon = True
    thread.start()
