import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta

TRADE_LOG_FILE = "trade_logs.json"

# ------------------ Trade Logging ------------------ #
def load_trades():
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_trade(trade):
    trades = load_trades()
    trades.append(trade)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def get_trade_logs(limit=30):
    trades = load_trades()
    return trades[-limit:] if trades else []

def get_results():
    trades = load_trades()
    wins = sum(1 for t in trades if t.get("result") == "win")
    losses = sum(1 for t in trades if t.get("result") == "loss")
    total = len(trades)
    win_rate = (wins / total) * 100 if total > 0 else 0
    return wins, losses, total, round(win_rate, 2)

# ------------------ Data Fetchers ------------------ #
def fetch_mexc_data():
    """Try MEXC v3 kline data first (no symbol param), fallback to v2 API."""
    try:
        url_v3 = "https://www.mexc.com/open/api/v3/market/kline?symbol=BTC_USDT&interval=5m&limit=200"
        r = requests.get(url_v3, timeout=10)
        if r.status_code == 200 and "data" in r.json():
            data = r.json()["data"]
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df
    except Exception:
        pass  # fallback to v2

    try:
        url_v2 = "https://www.mexc.com/open/api/v2/market/kline?symbol=BTC_USDT&type=5min&limit=200"
        r = requests.get(url_v2, timeout=10)
        if r.status_code == 200 and "data" in r.json():
            data = r.json()["data"]
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df
    except Exception:
        pass
    return None

def fetch_bybit_data():
    try:
        url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=5&limit=200"
        r = requests.get(url, timeout=10)
        if r.status_code == 200 and "result" in r.json():
            data = r.json()["result"]["list"]
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
            df = df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float})
            return df
    except Exception:
        pass
    return None

def check_data_source():
    df = fetch_mexc_data()
    if df is not None:
        return "✅ Connected to MEXC"
    df = fetch_bybit_data()
    if df is not None:
        return "✅ Connected to Bybit"
    return "❌ Failed to connect to both MEXC and Bybit"

# ------------------ Signal Logic ------------------ #
def calculate_indicators(df):
    df["ema_fast"] = df["close"].ewm(span=9).mean()
    df["ema_slow"] = df["close"].ewm(span=21).mean()
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    df["rsi"] = compute_rsi(df["close"], 14)
    return df

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean()
    rs = ma_up / ma_down
    return 100 - (100 / (1 + rs))

def detect_signal(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    if latest["ema_fast"] > latest["ema_slow"] and latest["ema_fast"] > latest["vwap"] and prev["ema_fast"] <= prev["ema_slow"]:
        return "long"
    elif latest["ema_fast"] < latest["ema_slow"] and latest["ema_fast"] < latest["vwap"] and prev["ema_fast"] >= prev["ema_slow"]:
        return "short"
    return None

# ------------------ Market Scan ------------------ #
def scan_market():
    df = fetch_mexc_data()
    if df is None:
        df = fetch_bybit_data()
    if df is None:
        return "❌ Data Error", "No data from MEXC or Bybit."

    df = calculate_indicators(df)
    signal = detect_signal(df)
    if signal:
        price = df.iloc[-1]["close"]
        sl = price - 300 if signal == "long" else price + 300
        tp1 = price + 600 if signal == "long" else price - 600
        tp2 = price + 1500 if signal == "long" else price - 1500
        trade = {
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "signal": signal,
            "price": price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "result": None
        }
        save_trade(trade)
        return f"🚨 {signal.upper()} Signal", f"Entry: {price}\nSL: {sl}\nTP: {tp1} → {tp2}"
    else:
        return None, "No signal at the moment."
