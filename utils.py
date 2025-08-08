import os, time, json, datetime
import requests
import pandas as pd
import numpy as np

TRADE_LOG_FILE = "trade_logs.json"

# ---------- HTTP hardening ----------
REQUEST_HEADERS = {"User-Agent": "SpiralBot/1.0 (+render)"}

def _safe_json(resp):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "application/json" not in ctype:
        return None
    txt = (resp.text or "").strip()
    if not txt:
        return None
    try:
        return resp.json()
    except Exception:
        return None

# ---------- Trade logs ----------
def load_trades():
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump([], f)
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_trades(trades):
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def log_trade(entry_price, direction, sl, tp, score, outcome=None):
    trades = load_trades()
    trades.append({
        "time": datetime.datetime.utcnow().isoformat(),
        "entry": float(entry_price),
        "direction": direction,
        "sl": float(sl),
        "tp": float(tp),
        "score": float(score),
        "outcome": outcome or ""
    })
    save_trades(trades)

def get_trade_logs():
    return load_trades()[-30:]

def get_results():
    trades = load_trades()
    if not trades:
        return [0, 0, 0, 0]
    wins = [t for t in trades if t.get("outcome") == "win"]
    win_rate = round(len(wins) / len(trades) * 100, 2)
    avg_score = round(np.mean([t.get("score", 0) for t in trades]), 2)
    return [len(trades), len(wins), win_rate, avg_score]

# ---------- Data fetch (hardened) ----------
def fetch_bybit_data(interval="5", limit=200, retries=2):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": "BTCUSDT", "interval": interval, "limit": min(int(limit), 200)}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=8)
            j = _safe_json(r)
            if j and "result" in j and "list" in j["result"] and j["result"]["list"]:
                df = pd.DataFrame(j["result"]["list"], columns=["time","open","high","low","close","volume","turnover"])
                for col in ("open","high","low","close"):
                    df[col] = df[col].astype(float)
                return df
        except Exception:
            pass
        time.sleep(0.3)
    return None

def fetch_mexc_data(interval="5m", limit=200, retries=2):
    url = "https://www.mexc.com/open/api/v2/market/kline"
    params = {"symbol": "BTC_USDT", "interval": interval, "limit": min(int(limit), 500)}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=8)
            j = _safe_json(r)
            if j and "data" in j and isinstance(j["data"], list) and j["data"]:
                df = pd.DataFrame(j["data"], columns=["time","open","high","low","close","volume"])
                for col in ("open","high","low","close"):
                    df[col] = df[col].astype(float)
                return df
        except Exception:
            pass
        time.sleep(0.3)
    return None

def check_data_source():
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

# ---------- Indicators ----------
def calculate_vwap(df):
    # VWAP proxy using close*volume
    cum_q = (df["close"] * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum()
    # Avoid div/0
    vwap = cum_q / cum_v.replace(0, np.nan)
    vwap = vwap.fillna(df["close"])
    return vwap

def calculate_ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()

def detect_engulfing(df):
    out = [None]
    for i in range(1, len(df)):
        o1, c1 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o2, c2 = df["open"].iloc[i],   df["close"].iloc[i]
        prev_body = abs(c1 - o1)
        curr_body = abs(c2 - o2)
        bull = (c2 > o2) and (o2 < c1) and (c2 > o1) and (curr_body > prev_body)
        bear = (c2 < o2) and (o2 > c1) and (c2 < o1) and (curr_body > prev_body)
        out.append("bullish" if bull else "bearish" if bear else None)
    return out

def calculate_rsi(df, period=14):
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

# ---------- Scanner ----------
def scan_market():
    df = fetch_bybit_data()
    source = "BYBIT"
    if df is None:
        df = fetch_mexc_data()
        source = "MEXC"
    if df is None:
        return None, "❌ Data Error:\nCouldn’t parse JSON from Bybit/MEXC (temporary upstream issue). Try /forcescan again."

    df["vwap"] = calculate_vwap(df)
    df["ema_fast"] = calculate_ema(df, 9)
    df["ema_slow"] = calculate_ema(df, 21)
    df["rsi"] = calculate_rsi(df)
    df["engulfing"] = detect_engulfing(df)

    latest = df.iloc[-1]
    signal = None
    score = 0.0

    long_ok  = latest["ema_fast"] > latest["ema_slow"] and latest["close"] > latest["vwap"] and latest["engulfing"] == "bullish" and latest["rsi"] > 50
    short_ok = latest["ema_fast"] < latest["ema_slow"] and latest["close"] < latest["vwap"] and latest["engulfing"] == "bearish" and latest["rsi"] < 50

    if long_ok:
        signal = "LONG";  score = 2.5
    elif short_ok:
        signal = "SHORT"; score = 2.5

    if signal:
        entry = float(latest["close"])
        sl = entry - 300 if signal == "LONG" else entry + 300
        tp = entry + 600 if signal == "LONG" else entry - 600
        log_trade(entry, signal, sl, tp, score)
        return f"🚨 {signal} ({source})\nEntry: {round(entry)}\nSL: {round(sl)}  TP: {round(tp)}\nScore: {score}", None
    else:
        return None, f"No signal at the moment. ({source})"

# ---------- Backtest (simple, non-chunked) ----------
def run_backtest_stream(days=2):
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

    lines = []
    active = None
    for i in range(21, len(df)):
        row = df.iloc[i]
        price = float(row["close"])

        if active:
            if active["dir"] == "LONG":
                if price >= active["tp"]:
                    lines.append(f"✅ TP hit @ {round(price)} (+$600)")
                    log_trade(active["entry"], "LONG", active["sl"], active["tp"], 2.5, outcome="win")
                    active = None
                elif price <= active["sl"]:
                    lines.append(f"❌ SL hit @ {round(price)} (-$300)")
                    log_trade(active["entry"], "LONG", active["sl"], active["tp"], 2.5, outcome="loss")
                    active = None
            else:
                if price <= active["tp"]:
                    lines.append(f"✅ TP hit @ {round(price)} (+$600)")
                    log_trade(active["entry"], "SHORT", active["sl"], active["tp"], 2.5, outcome="win")
                    active = None
                elif price >= active["sl"]:
                    lines.append(f"❌ SL hit @ {round(price)} (-$300)")
                    log_trade(active["entry"], "SHORT", active["sl"], active["tp"], 2.5, outcome="loss")
                    active = None

        if not active:
            long_ok  = row["ema_fast"] > row["ema_slow"] and row["close"] > row["vwap"] and row["engulfing"] == "bullish" and row["rsi"] > 50
            short_ok = row["ema_fast"] < row["ema_slow"] and row["close"] < row["vwap"] and row["engulfing"] == "bearish" and row["rsi"] < 50
            if long_ok or short_ok:
                direction = "LONG" if long_ok else "SHORT"
                entry = price
                sl = entry - 300 if direction == "LONG" else entry + 300
                tp = entry + 600 if direction == "LONG" else entry - 600
                active = {"dir": direction, "entry": entry, "sl": sl, "tp": tp}
                lines.append(f"{'🟢 LONG' if direction=='LONG' else '🔴 SHORT'} entry @ {round(entry)}")

    return lines
