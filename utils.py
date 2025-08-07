import os
import requests
from datetime import datetime
import json

TRADE_LOG = []
ACTIVE_TRADE = None

def get_data():
    symbol = "BTCUSDT"
    interval = "5m"
    limit = 100
    bybit_url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"

    try:
        response = requests.get(bybit_url)
        data = response.json()
        if "result" in data and "list" in data["result"]:
            return data["result"]["list"]
        else:
            raise Exception("No 'list' in response")
    except Exception:
        # Fallback to MEXC
        try:
            mexc_url = f"https://www.mexc.com/open/api/v2/market/kline?symbol={symbol}&interval=5m&limit={limit}"
            response = requests.get(mexc_url)
            data = response.json()
            return data["data"]
        except Exception as e:
            return None

def analyze(data):
    global ACTIVE_TRADE

    if not data:
        return "❌ Error: Failed to fetch data"

    last_candle = data[-1]
    open_price = float(last_candle[1])
    close_price = float(last_candle[2])
    high = float(last_candle[3])
    low = float(last_candle[4])

    vwap = (high + low + close_price) / 3
    rsi = 50  # Placeholder for RSI logic
    trend_up = close_price > vwap
    wick_percent = abs(low - open_price) / (high - low + 1e-6) * 100

    if ACTIVE_TRADE:
        return "⏳ Active trade in progress. No new entries."

    if trend_up and rsi < 30 and wick_percent > 20:
        ACTIVE_TRADE = {
            "entry": close_price,
            "side": "LONG",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        TRADE_LOG.append({**ACTIVE_TRADE, "status": "OPEN"})
        return (
            f"🚨 LONG Signal\nEntry: {close_price}\nVWAP: {vwap:.2f}\n"
            f"RSI: {rsi}\nWick: {wick_percent:.1f}%\nMomentum: STRONG"
        )
    elif not trend_up and rsi > 70 and wick_percent > 20:
        ACTIVE_TRADE = {
            "entry": close_price,
            "side": "SHORT",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        TRADE_LOG.append({**ACTIVE_TRADE, "status": "OPEN"})
        return (
            f"🚨 SHORT Signal\nEntry: {close_price}\nVWAP: {vwap:.2f}\n"
            f"RSI: {rsi}\nWick: {wick_percent:.1f}%\nMomentum: STRONG"
        )
    else:
        return "🔍 No signal. Setup not strong."

def scan_market():
    data = get_data()
    return analyze(data)

def get_trade_logs():
    if not TRADE_LOG:
        return "📭 No trades yet."
    logs = ""
    for trade in TRADE_LOG[-30:]:
        logs += f"{trade['timestamp']} | {trade['side']} @ {trade['entry']} | Status: {trade['status']}\n"
    return logs

def get_results_summary():
    wins = sum(1 for t in TRADE_LOG if t["status"] == "WIN")
    losses = sum(1 for t in TRADE_LOG if t["status"] == "LOSS")
    total = wins + losses
    if total == 0:
        return "📊 No completed trades yet."
    win_rate = round(wins / total * 100, 2)
    return f"✅ Wins: {wins}\n❌ Losses: {losses}\n🎯 Win Rate: {win_rate}%"

def get_bot_status():
    return (
        "📌 SpiralBot Strategy\n"
        "- 5m candle signals\n"
        "- RSI + VWAP + Wick logic\n"
        "- $300 SL / $600–1500 TP\n"
        "- AI exit coming soon\n"
    )

def check_data_connection():
    data = get_data()
    if not data:
        return "❌ Data Error:\n❌ Failed to fetch from Bybit & MEXC"
    return "✅ Data connection working (Bybit or MEXC)"
