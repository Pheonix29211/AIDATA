import requests
import json
import time
from datetime import datetime
import os

TRADE_LOG_FILE = "trade_logs.json"

# ===== CONFIGURATION =====
BYBIT_SYMBOL = "BTCUSDT"
MEXC_SYMBOL = "BTC_USDT"
RSI_PERIOD = 14
VWAP_PERIOD = 20
LIQUIDATION_THRESHOLD = 250000
TP_RANGE = [600, 1500]  # in $
SL_LIMIT = 300  # in $
CONFIDENCE_THRESHOLD = 2.0
PING_INTERVAL = 60  # seconds

def get_bybit_data():
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={BYBIT_SYMBOL}&interval=5&limit=100"
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        return data["result"]["list"] if "result" in data else None
    except Exception:
        return None

def get_mexc_data():
    url = f"https://www.mexc.com/open/api/v2/market/kline?symbol={MEXC_SYMBOL}&interval=5m&limit=100"
    try:
        res = requests.get(url, timeout=5)
        data = res.json()
        return data["data"] if "data" in data else None
    except Exception:
        return None

def get_chart_data():
    data = get_bybit_data()
    if data:
        return "bybit", data
    data = get_mexc_data()
    if data:
        return "mexc", data
    return None, None

def calculate_rsi(data, period=RSI_PERIOD):
    closes = [float(c[4]) for c in data][-period-1:]
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-delta)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)

def calculate_wick(data):
    latest = data[-1]
    open_, high, low, close = map(float, [latest[1], latest[2], latest[3], latest[4]])
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    upper_perc = (upper_wick / body * 100) if body != 0 else 0
    lower_perc = (lower_wick / body * 100) if body != 0 else 0
    return round(upper_perc, 2), round(lower_perc, 2)

def get_liquidation_proxy():
    try:
        # Mock or adapt this with real Coinglass or MEXC inferred data if available
        return 280000  # Simulated
    except Exception:
        return 0

def calculate_score(rsi, wick_low, wick_high, liquidation):
    score = 0
    if rsi < 25:
        score += 1
    if wick_low > 20:
        score += 0.8
    if liquidation > LIQUIDATION_THRESHOLD:
        score += 0.7
    return round(score, 2)

def detect_engulfing(data):
    c1 = data[-2]
    c2 = data[-1]
    o1, c1 = float(c1[1]), float(c1[4])
    o2, c2 = float(c2[1]), float(c2[4])
    bullish = o1 > c1 and o2 > o1 and c2 > o1
    bearish = o1 < c1 and o2 < o1 and c2 < o1
    return bullish, bearish

def get_latest_price(data):
    return float(data[-1][4])

def get_vwap(data):
    closes = [float(c[4]) for c in data][-VWAP_PERIOD:]
    volumes = [float(c[5]) for c in data][-VWAP_PERIOD:]
    typical_prices = [(float(c[2]) + float(c[3]) + float(c[4])) / 3 for c in data][-VWAP_PERIOD:]
    total_tpv = sum(p * v for p, v in zip(typical_prices, volumes))
    total_volume = sum(volumes)
    return total_tpv / total_volume if total_volume != 0 else closes[-1]

def get_ema(data, period):
    closes = [float(c[4]) for c in data][-period:]
    k = 2 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return ema

def save_trade(trade):
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump([], f)
    with open(TRADE_LOG_FILE, "r") as f:
        logs = json.load(f)
    logs.append(trade)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(logs[-100:], f)

def get_trade_logs():
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    with open(TRADE_LOG_FILE, "r") as f:
        return json.load(f)

def get_results():
    logs = get_trade_logs()
    wins = [t for t in logs if t.get("outcome") == "win"]
    losses = [t for t in logs if t.get("outcome") == "loss"]
    total = len(logs)
    win_rate = round(len(wins) / total * 100, 2) if total else 0
    avg_score = round(sum(t["score"] for t in logs) / total, 2) if total else 0
    return win_rate, len(wins), len(losses), avg_score

def check_data_source():
    source, data = get_chart_data()
    if not data:
        return "❌ Error: Failed to fetch data"
    return f"✅ Connected to {source.upper()}"

def scan_market():
    source, data = get_chart_data()
    if not data:
        return None, "❌ Error: Failed to fetch data"

    rsi = calculate_rsi(data)
    wick_up, wick_down = calculate_wick(data)
    liq = get_liquidation_proxy()
    bullish_engulfing, bearish_engulfing = detect_engulfing(data)
    price = get_latest_price(data)
    vwap = get_vwap(data)
    ema_5 = get_ema(data, 5)
    ema_20 = get_ema(data, 20)

    trend_up = price > vwap
    trend_down = price < vwap

    long_signal = trend_up and rsi < 30 and wick_down > 20 and bullish_engulfing
    short_signal = trend_down and rsi > 70 and wick_up > 20 and bearish_engulfing

    score_long = calculate_score(rsi, wick_down, wick_up, liq)
    score_short = calculate_score(100 - rsi, wick_up, wick_down, liq)

    trade = {
        "timestamp": time.time(),
        "price": price,
        "rsi": rsi,
        "wick_up": wick_up,
        "wick_down": wick_down,
        "liq": liq,
        "vwap": vwap,
        "ema_5": ema_5,
        "ema_20": ema_20,
        "score": score_long if long_signal else score_short,
        "type": "long" if long_signal else "short" if short_signal else None,
        "outcome": None
    }

    if long_signal or short_signal:
        save_trade(trade)
        direction = "BUY 🟢" if long_signal else "SELL 🔴"
        return trade, f"""
🚨 {direction} Signal
Entry: {price}
RSI: {rsi} | Wick%: {wick_down if long_signal else wick_up}%
Liq: ${liq:,}
Score: {trade['score']} → Strong setup
TP: +{TP_RANGE[0]} to +{TP_RANGE[1]} | SL: -{SL_LIMIT}
"""
    return None, "No signal at the moment."
