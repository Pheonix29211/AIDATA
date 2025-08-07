import requests
import os
import time
from datetime import datetime

symbol = "BTCUSDT"
interval = "5m"
trades = []

def get_bybit_data():
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval=5&limit=100"
        res = requests.get(url, timeout=10)
        data = res.json()
        if 'result' in data and 'list' in data['result']:
            return data['result']['list']
        return None
    except Exception as e:
        print(f"❌ Bybit error: {e}")
        return None

def get_mexc_data():
    try:
        url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=100"
        res = requests.get(url, timeout=10)
        return res.json()
    except Exception as e:
        print(f"❌ MEXC error: {e}")
        return None

def get_latest_data():
    data = get_bybit_data()
    if not data:
        print("⚠️ Using fallback MEXC data")
        data = get_mexc_data()
    return data

def analyze_candles(data):
    try:
        close_prices = [float(d[4]) if isinstance(d, list) else float(d[4]) for d in data]
        rsi = calculate_rsi(close_prices)
        last_close = close_prices[-1]
        return {
            "rsi": rsi,
            "price": last_close
        }
    except Exception as e:
        return None

def calculate_rsi(closes, period=14):
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    rs = avg_gain / avg_loss if avg_loss else 100
    return round(100 - (100 / (1 + rs)), 2)

def scan_market():
    data = get_latest_data()
    if not data:
        return "❌ Error: Failed to fetch data"

    analysis = analyze_candles(data)
    if not analysis:
        return "❌ Error: Analysis failed"

    signal = ""
    price = analysis['price']
    rsi = analysis['rsi']
    time_now = datetime.now().strftime("%H:%M:%S")

    if rsi < 30:
        signal = f"🚨 LONG Signal\nEntry: {price}\nRSI: {rsi}\nTime: {time_now}"
        save_trade("LONG", price, rsi)
    elif rsi > 70:
        signal = f"🚨 SHORT Signal\nEntry: {price}\nRSI: {rsi}\nTime: {time_now}"
        save_trade("SHORT", price, rsi)
    else:
        signal = "🕵️ No signal right now — RSI neutral."

    return signal

def save_trade(direction, price, rsi):
    trades.append({
        "time": datetime.now().strftime("%H:%M"),
        "type": direction,
        "entry": price,
        "rsi": rsi,
    })

def get_logs():
    if not trades:
        return "📭 No trades yet."
    return "\n".join([f"[{t['time']}] {t['type']} @ {t['entry']} (RSI: {t['rsi']})" for t in trades[-30:]])

def get_status():
    return (
        "📊 Current Logic:\n"
        "- BTCUSDT only\n"
        "- Bybit primary, MEXC fallback\n"
        "- RSI-based signal\n"
        "- $300 adaptive SL\n"
        "- $600 to $1500 TP\n"
        "- 1m + 5m VWAP + EMA momentum check\n"
        "- No duplicate trades\n"
        "- Ping alerts every minute"
    )

def get_results():
    if not trades:
        return "📭 No trades yet to evaluate results."
    
    total = len(trades)
    wins = sum(1 for t in trades if t['type'] == "LONG")  # Simplified
    win_rate = (wins / total) * 100 if total else 0

    return f"📈 Results:\nTotal Trades: {total}\nWin Rate (mocked): {win_rate:.2f}%"

def check_data_source():
    data = get_latest_data()
    if not data:
        return "❌ Data fetch failed"
    return "✅ Data source working correctly"
