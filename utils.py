import requests
import json
import os
import datetime
import time
import numpy as np
import pandas as pd

TRADE_LOG_FILE = "trade_logs.json"

# -------------------- Helper Functions -------------------- #

def load_trades():
    """Load trade logs from file."""
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump([], f)
    with open(TRADE_LOG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_trades(trades):
    """Save trade logs to file."""
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def log_trade(entry_price, direction, sl, tp, score, outcome=None):
    """Log a new trade."""
    trades = load_trades()
    trade = {
        "time": datetime.datetime.utcnow().isoformat(),
        "entry": entry_price,
        "direction": direction,
        "sl": sl,
        "tp": tp,
        "score": score,
        "outcome": outcome
    }
    trades.append(trade)
    save_trades(trades)

def get_trade_logs():
    """Return the last 30 trades."""
    trades = load_trades()
    return trades[-30:]

def get_results():
    """Return win rate, total trades, avg score, profitability."""
    trades = load_trades()
    if not trades:
        return [0, 0, 0, 0]
    wins = [t for t in trades if t.get("outcome") == "win"]
    win_rate = round(len(wins) / len(trades) * 100, 2)
    avg_score = round(np.mean([t.get("score", 0) for t in trades]), 2)
    profit = len(wins) * 1 - (len(trades) - len(wins)) * 1
    return [len(trades), len(wins), win_rate, avg_score]

# -------------------- Data Fetch -------------------- #

def fetch_bybit_data(interval="5", limit=200):
    """Fetch historical kline data from Bybit."""
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": "BTCUSDT", "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=8)
    data = r.json()
    if "result" in data and "list" in data["result"]:
        df = pd.DataFrame(data["result"]["list"], columns=["time","open","high","low","close","volume","turnover"])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        return df
    return None

def fetch_mexc_data(interval="5m", limit=200):
    """Fetch historical kline data from MEXC."""
    url = "https://www.mexc.com/open/api/v2/market/kline"
    params = {"symbol": "BTC_USDT", "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=8)
    data = r.json()
    if "data" in data:
        df = pd.DataFrame(data["data"], columns=["time","open","high","low","close","volume"])
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        return df
    return None

def check_data_source():
    """Quick health check for /check_data."""
    try:
        if fetch_bybit_data(limit=2) is not None:
            return "✅ Connected to BYBIT"
    except Exception:
        pass
    try:
        if fetch_mexc_data(limit=2) is not None:
            return "✅ Connected to MEXC"
    except Exception:
        pass
    return "❌ Error: Failed to fetch data"

# -------------------- Strategy Logic -------------------- #

def calculate_vwap(df):
    """Calculate VWAP."""
    q = df["close"] * df["volume"]
    return q.cumsum() / df["volume"].cumsum()

def calculate_ema(df, period):
    """Calculate EMA."""
    return df["close"].ewm(span=period, adjust=False).mean()

def detect_engulfing(df):
    """Detect bullish/bearish engulfing patterns."""
    engulfing = []
    for i in range(1, len(df)):
        prev_body = abs(df["close"][i-1] - df["open"][i-1])
        curr_body = abs(df["close"][i] - df["open"][i])
        if df["close"][i] > df["open"][i] and df["open"][i] < df["close"][i-1] and curr_body > prev_body:
            engulfing.append("bullish")
        elif df["close"][i] < df["open"][i] and df["open"][i] > df["close"][i-1] and curr_body > prev_body:
            engulfing.append("bearish")
        else:
            engulfing.append(None)
    engulfing.insert(0, None)
    return engulfing

def calculate_rsi(df, period=14):
    """Calculate RSI."""
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# -------------------- Market Scan -------------------- #

def scan_market():
    """Scan for trade setup."""
    df = fetch_bybit_data()
    if df is None:
        df = fetch_mexc_data()
        if df is None:
            return None, "❌ No data from both sources"

    df["vwap"] = calculate_vwap(df)
    df["ema_fast"] = calculate_ema(df, 9)
    df["ema_slow"] = calculate_ema(df, 21)
    df["rsi"] = calculate_rsi(df)
    df["engulfing"] = detect_engulfing(df)

    latest = df.iloc[-1]
    signal = None
    score = 0

    if latest["ema_fast"] > latest["ema_slow"] and latest["close"] > latest["vwap"] and latest["engulfing"] == "bullish" and latest["rsi"] > 50:
        signal = "LONG"
        score = 2.5
    elif latest["ema_fast"] < latest["ema_slow"] and latest["close"] < latest["vwap"] and latest["engulfing"] == "bearish" and latest["rsi"] < 50:
        signal = "SHORT"
        score = 2.5

    if signal:
        sl = latest["close"] - 300 if signal == "LONG" else latest["close"] + 300
        tp = latest["close"] + 600 if signal == "LONG" else latest["close"] - 600
        log_trade(latest["close"], signal, sl, tp, score)
        return f"🚨 {signal} Signal\nEntry: {latest['close']}\nSL: {sl}\nTP: {tp}\nScore: {score}", None
    else:
        return None, "No signal at the moment."

# -------------------- Backtest -------------------- #

def run_backtest_stream(days=2):
    """Backtest last X days in streaming style."""
    df = fetch_bybit_data(limit=200)
    if df is None:
        df = fetch_mexc_data(limit=200)
    if df is None:
        return ["❌ Backtest: unable to fetch history from Bybit or MEXC."]

    df["vwap"] = calculate_vwap(df)
    df["ema_fast"] = calculate_ema(df, 9)
    df["ema_slow"] = calculate_ema(df, 21)
    df["rsi"] = calculate_rsi(df)
    df["engulfing"] = detect_engulfing(df)

    results = []
    for i in range(21, len(df)):
        latest = df.iloc[i]
        if latest["ema_fast"] > latest["ema_slow"] and latest["close"] > latest["vwap"] and latest["engulfing"] == "bullish" and latest["rsi"] > 50:
            results.append(f"{latest['time']}: LONG at {latest['close']}")
        elif latest["ema_fast"] < latest["ema_slow"] and latest["close"] < latest["vwap"] and latest["engulfing"] == "bearish" and latest["rsi"] < 50:
            results.append(f"{latest['time']}: SHORT at {latest['close']}")
    return results
