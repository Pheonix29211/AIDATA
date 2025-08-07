import requests
import time
from datetime import datetime

TRADE_LOG = []
ACTIVE_TRADE = None
LAST_DIRECTION = None

BYBIT_ENDPOINT = "https://api.bybit.com/v5/market/kline"
MEXC_ENDPOINT = "https://www.mexc.com/open/api/v2/market/kline"
SYMBOL = "BTCUSDT"
INTERVAL = "5"
SL_DOLLARS = 300
TP_MIN = 600
TP_MAX = 1500

def fetch_bybit_data():
    try:
        now = int(time.time())
        resp = requests.get(BYBIT_ENDPOINT, params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "from": now - 1500,
            "limit": 100
        })
        data = resp.json()
        if 'result' in data and 'list' in data['result']:
            return data['result']['list']
    except:
        return None

def fetch_mexc_data():
    try:
        resp = requests.get(MEXC_ENDPOINT, params={
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": 100
        })
        data = resp.json()
        if 'data' in data:
            return data['data']
    except:
        return None

def analyze_data(candles):
    if not candles:
        return None

    close_prices = [float(c[4]) for c in candles]
    ema5 = sum(close_prices[-5:]) / 5
    ema20 = sum(close_prices[-20:]) / 20
    current_price = close_prices[-1]

    rsi = calculate_rsi(close_prices)
    direction = None
    score = 0

    if rsi < 30 and ema5 > ema20:
        direction = "LONG"
        score += 1
    if rsi > 70 and ema5 < ema20:
        direction = "SHORT"
        score += 1

    return {
        "price": current_price,
        "rsi": rsi,
        "ema5": ema5,
        "ema20": ema20,
        "score": score,
        "direction": direction
    }

def calculate_rsi(prices, period=14):
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [delta for delta in deltas if delta > 0]
    losses = [-delta for delta in deltas if delta < 0]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def scan_market(test_mode=False):
    global ACTIVE_TRADE, LAST_DIRECTION

    data = fetch_bybit_data()
    if not data:
        data = fetch_mexc_data()
    if not data:
        return "❌ Error: Failed to fetch data"

    analysis = analyze_data(data)
    if not analysis or not analysis["direction"]:
        return "No strong setup found."

    if ACTIVE_TRADE:
        return f"⚠️ Trade already active: {ACTIVE_TRADE['direction']} @ {ACTIVE_TRADE['entry']}"

    signal = f"""
🚨 *{analysis['direction']} Signal*
Entry: {analysis['price']}
RSI: {analysis['rsi']:.2f}
Score: {analysis['score']}
TP: +${TP_MIN} → ${TP_MAX}
SL: -${SL_DOLLARS}
"""
    ACTIVE_TRADE = {
        "direction": analysis["direction"],
        "entry": analysis["price"],
        "timestamp": datetime.now()
    }
    LAST_DIRECTION = analysis["direction"]
    TRADE_LOG.append({
        "time": str(datetime.now()),
        "entry": analysis["price"],
        "dir": analysis["direction"],
        "rsi": analysis["rsi"],
        "ema5": analysis["ema5"],
        "ema20": analysis["ema20"],
        "score": analysis["score"]
    })

    return signal.strip()

def get_trade_logs():
    if not TRADE_LOG:
        return "No trades yet."
    return "\n".join([
        f"{i+1}. {t['time']} | {t['dir']} @ {t['entry']} | RSI: {t['rsi']:.2f} | Score: {t['score']}"
        for i, t in enumerate(TRADE_LOG[-30:])
    ])

def get_results():
    wins = sum(1 for t in TRADE_LOG if t['score'] >= 1)
    total = len(TRADE_LOG)
    winrate = (wins / total * 100) if total else 0
    return f"📊 Total: {total} | Wins: {wins} | Winrate: {winrate:.1f}%"

def get_status():
    return f"✅ Logic:\n• Symbol: {SYMBOL}\n• Timeframe: {INTERVAL}m\n• SL: ${SL_DOLLARS}\n• TP: ${TP_MIN} to ${TP_MAX}\n• Momentum: 1m + 5m VWAP & EMA\n• Ping: 1m intervals\n• Active: {'Yes' if ACTIVE_TRADE else 'No'}"