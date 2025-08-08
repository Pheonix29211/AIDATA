import os
import json
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

TRADE_LOG_FILE = "trade_logs.json"

# ---------------- HTTP hardening & diag ----------------
REQUEST_HEADERS = {"User-Agent": "SpiralBot/1.0 (+render)"}
LAST_FETCH_DEBUG = {"mexc": "", "bybit": ""}

def _safe_json(resp):
    txt = (resp.text or "").strip()
    if not txt:
        return None
    try:
        return resp.json()
    except Exception:
        return None

def quick_diag():
    m = LAST_FETCH_DEBUG.get("mexc","no call yet")
    b = LAST_FETCH_DEBUG.get("bybit","no call yet")
    return f"MEXC: {m}\nBYBIT: {b}"

# ---------------- Trade logs ----------------
def _ensure_log_file():
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump([], f)

def load_trades():
    _ensure_log_file()
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_trade(trade):
    trades = load_trades()
    trades.append(trade)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def get_trade_logs(limit=30):
    trades = load_trades()
    return trades[-limit:] if trades else []

def get_results():
    trades = load_trades()
    total = len(trades)
    if total == 0:
        return (0, 0, 0.0, 0.0)
    wins = sum(1 for t in trades if (t.get("result") or "").lower() == "win")
    win_rate = round(100.0 * wins / total, 2)
    scores = [float(t.get("score", 0.0)) for t in trades]
    avg_score = round(float(np.mean(scores)) if scores else 0.0, 2)
    return (total, wins, win_rate, avg_score)

# ---------------- Data fetchers ----------------
# ---------- Replace your existing fetchers with these ----------

def fetch_mexc_data(interval="5m", limit=200, retries=2):
    """
    MEXC-first, v3 only (v2 removed). Tries:
      1) Official v3 (spot): api.mexc.com/api/v3/klines  (BTCUSDT)
      2) Open v3 (spot):    www.mexc.com/open/api/v3/market/kline (BTC_USDT)
      3) Contract v1:       contract.mexc.com/api/v1/contract/kline (BTC_USDT, Min5)
    Returns DataFrame [time, open, high, low, close, volume] or None.
    """
    import requests, pandas as pd, time

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SpiralBot",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "keep-alive",
        "Origin": "https://www.mexc.com",
        "Referer": "https://www.mexc.com/",
    }
    lim = min(int(limit), 1000)

    # ---- (1) Official v3 (array) ----
    v3_url = "https://api.mexc.com/api/v3/klines"
    v3_params = {"symbol": "BTCUSDT", "interval": interval, "limit": lim}
    for _ in range(retries + 1):
        try:
            r = requests.get(v3_url, params=v3_params, headers=headers, timeout=10, allow_redirects=True)
            LAST_FETCH_DEBUG["mexc"] = f"v3-official {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            arr = _safe_json(r)
            if isinstance(arr, list) and arr:
                df = pd.DataFrame(arr, columns=[
                    "open_time","open","high","low","close","volume",
                    "close_time","qav","trades","taker_base","taker_quote","ignore"
                ])
                for col in ("open","high","low","close","volume"):
                    df[col] = df[col].astype(float)
                df["time"] = df["close_time"]
                return df[["time","open","high","low","close","volume"]]
        except Exception:
            pass
        time.sleep(0.25)

    # ---- (2) Open v3 (JSON object w/ 'data') ----
    v3_open_url = "https://www.mexc.com/open/api/v3/market/kline"
    v3_open_params = {"symbol": "BTC_USDT", "interval": interval, "limit": min(lim, 500)}
    for _ in range(retries + 1):
        try:
            r = requests.get(v3_open_url, params=v3_open_params, headers=headers, timeout=10, allow_redirects=True)
            LAST_FETCH_DEBUG["mexc"] = f"v3-open {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            j = _safe_json(r)
            if isinstance(j, dict) and isinstance(j.get("data"), list) and j["data"]:
                df = pd.DataFrame(j["data"], columns=["time","open","high","low","close","volume","turnover"])
                for col in ("open","high","low","close","volume"):
                    df[col] = df[col].astype(float)
                return df[["time","open","high","low","close","volume"]]
        except Exception:
            pass
        time.sleep(0.25)

    # ---- (3) MEXC Contract API (futures) ----
    # interval mapping: use 'Min5' for 5m, 'Min1' for 1m etc.
    interval_map = {"1m":"Min1","5m":"Min5","15m":"Min15","30m":"Min30","60m":"Min60"}
    c_interval = interval_map.get(interval, "Min5")
    c_url = "https://contract.mexc.com/api/v1/contract/kline"
    c_params = {"symbol": "BTC_USDT", "interval": c_interval, "limit": min(lim, 500)}
    for _ in range(retries + 1):
        try:
            r = requests.get(c_url, params=c_params, headers=headers, timeout=10, allow_redirects=True)
            LAST_FETCH_DEBUG["mexc"] = f"contract {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            j = _safe_json(r)
            # returns {"success":true,"code":0,"data":[ [ts,open,high,low,close,vol] ... ]}
            if j and isinstance(j.get("data"), list) and j["data"]:
                df = pd.DataFrame(j["data"], columns=["time","open","high","low","close","volume"])
                for col in ("open","high","low","close","volume"):
                    df[col] = df[col].astype(float)
                return df[["time","open","high","low","close","volume"]]
        except Exception:
            pass
        time.sleep(0.25)

    return None


def fetch_bybit_data(interval="5", limit=200, retries=2):
    """
    Bybit public klines (linear BTCUSDT).
    Cloudflare can 403; send stronger headers.
    Returns DataFrame [time, open, high, low, close, volume] or None.
    """
    import requests, pandas as pd, time
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": "BTCUSDT", "interval": interval, "limit": min(int(limit), 200)}
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SpiralBot",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.bybit.com",
        "Referer": "https://www.bybit.com/",
        "Connection": "keep-alive",
    }
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10, allow_redirects=True)
            LAST_FETCH_DEBUG["bybit"] = f"{r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            j = _safe_json(r)
            if j and "result" in j and "list" in j["result"] and j["result"]["list"]:
                df = pd.DataFrame(j["result"]["list"], columns=["time","open","high","low","close","volume","turnover"])
                for col in ("open","high","low","close","volume"):
                    df[col] = df[col].astype(float)
                return df[["time","open","high","low","close","volume"]]
        except Exception:
            pass
        time.sleep(0.25)
    return None


# (Optional) Binance as last-resort fallback — OFF by default.
def fetch_binance_data(interval="5m", limit=200, retries=1):
    """
    Binance spot klines (BTCUSDT). Only used if ALLOW_BINANCE=1.
    """
    if os.getenv("ALLOW_BINANCE", "0") != "1":
        return None
    import requests, pandas as pd, time
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": min(int(limit), 1000)}
    headers = {"User-Agent": "Mozilla/5.0 SpiralBot"}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            arr = _safe_json(r)
            if isinstance(arr, list) and arr:
                df = pd.DataFrame(arr, columns=[
                    "open_time","open","high","low","close","volume",
                    "close_time","qav","trades","tbbav","tbqav","ignore"
                ])
                for col in ("open","high","low","close","volume"):
                    df[col] = df[col].astype(float)
                df["time"] = df["close_time"]
                return df[["time","open","high","low","close","volume"]]
        except Exception:
            pass
        time.sleep(0.25)
    return None


def check_data_source():
    # Try MEXC first (v3 or contract)
    try:
        if fetch_mexc_data(limit=2) is not None:
            return "✅ Connected to MEXC"
    except Exception:
        pass
    # Then Bybit
    try:
        if fetch_bybit_data(limit=2) is not None:
            return "✅ Connected to BYBIT"
    except Exception:
        pass
    # Optional Binance
    try:
        if fetch_binance_data(limit=2) is not None:
            return "✅ Connected to BINANCE (fallback)"
    except Exception:
        pass
    # If all fail, show diag detail
    return "❌ Failed to connect to MEXC/BYBIT.\n\nDiag:\n" + quick_diag()


# ---------------- Indicators ----------------
def calculate_vwap(df):
    cum_q = (df["close"] * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return (cum_q / cum_v).fillna(df["close"])

def calculate_ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = (-delta.clip(upper=0))
    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean().replace(0, np.nan)
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

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

def _compute_indicators(df):
    df = df.copy()
    df["ema_fast"] = calculate_ema(df, 9)
    df["ema_slow"] = calculate_ema(df, 21)
    df["vwap"] = calculate_vwap(df)
    df["rsi"] = calculate_rsi(df["close"], 14)
    df["engulfing"] = detect_engulfing(df)
    return df

def detect_signal(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]

    long_ok = (
        latest["ema_fast"] > latest["ema_slow"] and
        latest["close"] > latest["vwap"] and
        latest["engulfing"] == "bullish" and
        latest["rsi"] > 50 and
        prev["ema_fast"] <= prev["ema_slow"]
    )
    short_ok = (
        latest["ema_fast"] < latest["ema_slow"] and
        latest["close"] < latest["vwap"] and
        latest["engulfing"] == "bearish" and
        latest["rsi"] < 50 and
        prev["ema_fast"] >= prev["ema_slow"]
    )

    if long_ok:
        return "long"
    if short_ok:
        return "short"
    return None

# ---------------- Scanner ----------------
def scan_market():
    df = fetch_mexc_data()
    source = "MEXC"
    if df is None:
        df = fetch_bybit_data()
        source = "BYBIT"
    if df is None or len(df) < 30:
        dbg = quick_diag()
        return None, f"❌ Data Error:\nNo data from MEXC or BYBIT.\n\nDiag:\n{dbg}\nTry /forcescan again."

    df = _compute_indicators(df)
    sig = detect_signal(df)
    if sig:
        price = float(df.iloc[-1]["close"])
        sl  = price - 300 if sig == "long" else price + 300
        tp1 = price + 600 if sig == "long" else price - 600
        tp2 = price + 1500 if sig == "long" else price - 1500
        score = 2.5  # placeholder

        save_trade({
            "time": datetime.utcnow().isoformat(),
            "signal": sig,
            "entry": price,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "score": score,
            "result": ""
        })

        title = f"🚨 {sig.upper()} Signal ({source})"
        body  = f"Entry: {round(price)}\nSL: {round(sl)}\nTP: {round(tp1)} → {round(tp2)}\nScore: {score}"
        return title, body

    return None, f"No signal at the moment. ({source})"

# ---------------- Backtest stream ----------------
def run_backtest_stream(days=2):
    df = fetch_mexc_data()
    source = "MEXC"
    if df is None:
        df = fetch_bybit_data()
        source = "BYBIT"
    if df is None or len(df) < 50:
        return [f"❌ Backtest: unable to fetch history from MEXC or BYBIT."]

    df = _compute_indicators(df)

    lines = []
    active = None  # {"dir","entry","sl","tp1","tp2"}

    for i in range(2, len(df)):
        row = df.iloc[i]
        price = float(row["close"])

        # manage open
        if active:
            if active["dir"] == "long":
                if price >= active["tp2"]:
                    lines.append(f"✅ TP2 hit @ {round(price)} (+$1500) [{source}]")
                    active = None
                elif price >= active["tp1"]:
                    lines.append(f"✅ TP1 hit @ {round(price)} (+$600) – holding for TP2 [{source}]")
                elif price <= active["sl"]:
                    lines.append(f"❌ SL hit @ {round(price)} (-$300) [{source}]")
                    active = None
            else:
                if price <= active["tp2"]:
                    lines.append(f"✅ TP2 hit @ {round(price)} (+$1500) [{source}]")
                    active = None
                elif price <= active["tp1"]:
                    lines.append(f"✅ TP1 hit @ {round(price)} (+$600) – holding for TP2 [{source}]")
                elif price >= active["sl"]:
                    lines.append(f"❌ SL hit @ {round(price)} (-$300) [{source}]")
                    active = None

        # look for new entry if flat
        if not active:
            seg = df.iloc[: i+1]
            sig = detect_signal(seg)
            if sig in ("long", "short"):
                entry = price
                sl  = entry - 300 if sig == "long" else entry + 300
                tp1 = entry + 600 if sig == "long" else entry - 600
                tp2 = entry + 1500 if sig == "long" else entry - 1500
                active = {"dir": sig, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2}
                lines.append(f"{'🟢 LONG' if sig=='long' else '🔴 SHORT'} entry @ {round(entry)} | SL {round(sl)} TP {round(tp1)}→{round(tp2)} [{source}]")

    if not lines:
        lines = ["(Backtest finished: no qualifying entries)"]
    return lines
