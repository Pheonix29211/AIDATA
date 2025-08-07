import os
import json
import time
import requests
from datetime import datetime

TRADE_LOG_FILE = "trades.json"
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
SL_USD = 300
TP_USD = 600
MAX_TP_USD = 1500

def fetch_price_from_bybit():
    try:
        url = f"https://api.bybit.com/v2/public/tickers?symbol={SYMBOL}"
        res = requests.get(url)
        price = float(res.json()['result'][0]['last_price'])
        return price
    except Exception:
        return None

def fetch_price_from_mexc():
    try:
        url = f"https://api.mexc.com/api/v3/ticker/price?symbol={SYMBOL}"
        res = requests.get(url)
        price = float(res.json()['price'])
        return price
    except Exception:
        return None

def fetch_price():
    price = fetch_price_from_bybit()
    return price if price else fetch_price_from_mexc()

def generate_trade_signal():
    price = fetch_price()
    if not price:
        return None, "❌ Error: Failed to fetch price"
    
    # Placeholder logic: You should replace this with actual indicator-based logic
    if int(time.time()) % 2 == 0:
        return {
            "direction": "LONG",
            "entry": price,
            "confidence": 8.4,
            "rsi": 28.6,
            "timestamp": datetime.utcnow().isoformat()
        }, None
    else:
        return {
            "direction": "SHORT",
            "entry": price,
            "confidence": 8.2,
            "rsi": 71.1,
            "timestamp": datetime.utcnow().isoformat()
        }, None

def save_trade(trade):
    trades = load_trades()
    trades.append(trade)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def load_trades():
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    with open(TRADE_LOG_FILE, "r") as f:
        return json.load(f)

def get_trade_logs(n=30):
    trades = load_trades()
    last_trades = trades[-n:]
    logs = ""
    for t in last_trades:
        logs += f"{t['timestamp']} | {t['direction']} @ ${t['entry']} | RSI: {t['rsi']} | Confidence: {t['confidence']} | Result: {t.get('result', 'N/A')}\n"
    return logs or "No trades logged yet."

def get_results():
    trades = load_trades()
    if not trades:
        return "No trades recorded."

    wins = [t for t in trades if t.get("result") == "WIN"]
    losses = [t for t in trades if t.get("result") == "LOSS"]
    total = len(trades)
    win_rate = (len(wins) / total) * 100 if total else 0
    avg_conf = sum([t['confidence'] for t in trades]) / total if total else 0

    return (
        f"📈 Results:\n"
        f"Total Trades: {total}\n"
        f"✅ Wins: {len(wins)}\n"
        f"❌ Losses: {len(losses)}\n"
        f"🏆 Win Rate: {win_rate:.2f}%\n"
        f"📊 Avg. Confidence: {avg_conf:.2f}"
    )

def check_data_source():
    bybit = fetch_price_from_bybit()
    if bybit:
        return f"✅ Bybit working: ${bybit:.2f}"
    mexc = fetch_price_from_mexc()
    if mexc:
        return f"⚠️ Bybit failed, using MEXC: ${mexc:.2f}"
    return "❌ Both Bybit and MEXC failed to fetch data"