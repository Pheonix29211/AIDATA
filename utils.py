import os
import json
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

TRADE_LOG_FILE = "trade_logs.json"

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 SpiralBot"}
LAST_FETCH_DEBUG = {"mexc": "", "okx": "", "binance": "", "bybit": ""}

def now_local():
    tz = os.getenv("TIMEZONE", "Asia/Kolkata")
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.utcnow()

def _safe_json(resp):
    txt = (resp.text or "").strip()
    if not txt:
        return None
    try:
        return resp.json()
    except Exception:
        return None

def quick_diag():
    return (
        f"MEXC: {LAST_FETCH_DEBUG.get('mexc','no call yet')}\n"
        f"OKX: {LAST_FETCH_DEBUG.get('okx','no call yet')}\n"
        f"BINANCE: {LAST_FETCH_DEBUG.get('binance','no call yet')}\n"
        f"BYBIT: {LAST_FETCH_DEBUG.get('bybit','no call yet')}"
    )

# -------- trade logs ----------
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
    t = load_trades()
    return t[-limit:] if t else []

def get_results():
    t = load_trades()
    total = len(t)
    if total == 0:
        return (0, 0, 0.0, 0.0)
    wins = sum(1 for x in t if (x.get("result") or "").lower() == "win")
    win_rate = round(100.0 * wins / total, 2)
    scores = [float(x.get("score", 0.0)) for x in t]
    avg_score = round(float(np.mean(scores)) if scores else 0.0, 2)
    return (total, wins, win_rate, avg_score)

# -------- data fetchers (UNCHANGED) ----------
def fetch_mexc_data(interval="5m", limit=200, retries=2):
    headers = {
        "User-Agent": "Mozilla/5.0 SpiralBot",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "keep-alive",
    }
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": min(int(limit), 1000)}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10, allow_redirects=True)
            LAST_FETCH_DEBUG["mexc"] = f"v3-official {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            arr = _safe_json(r)
            if isinstance(arr, list) and arr:
                df_raw = pd.DataFrame(arr)
                open_   = pd.to_numeric(df_raw.iloc[:,1], errors="coerce")
                high_   = pd.to_numeric(df_raw.iloc[:,2], errors="coerce")
                low_    = pd.to_numeric(df_raw.iloc[:,3], errors="coerce")
                close_  = pd.to_numeric(df_raw.iloc[:,4], errors="coerce")
                volume_ = pd.to_numeric(df_raw.iloc[:,5], errors="coerce")
                timecol = df_raw.iloc[:,6] if df_raw.shape[1] >= 7 else df_raw.iloc[:,0]
                time_   = pd.to_numeric(timecol, errors="coerce").astype("Int64")
                df = pd.DataFrame({"time": time_, "open": open_, "high": high_, "low": low_, "close": close_, "volume": volume_}).dropna()
                if len(df) > 0:
                    df["time"] = df["time"].astype("int64")
                    return df
        except Exception:
            pass
        time.sleep(0.25)
    return None

def fetch_okx_data(interval="5m", limit=200, retries=2):
    bar_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "1H"}
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId": "BTC-USDT", "bar": bar_map.get(interval,"5m"), "limit": min(int(limit), 300)}
    headers = {"User-Agent": "Mozilla/5.0 SpiralBot", "Accept": "application/json"}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            LAST_FETCH_DEBUG["okx"] = f"OKX {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            j = _safe_json(r)
            if j and j.get("code") == "0" and j.get("data"):
                arr = j["data"][::-1]
                df_raw = pd.DataFrame(arr)
                df = pd.DataFrame({
                    "time":   pd.to_numeric(df_raw.iloc[:,0], errors="coerce").astype("int64"),
                    "open":   pd.to_numeric(df_raw.iloc[:,1], errors="coerce"),
                    "high":   pd.to_numeric(df_raw.iloc[:,2], errors="coerce"),
                    "low":    pd.to_numeric(df_raw.iloc[:,3], errors="coerce"),
                    "close":  pd.to_numeric(df_raw.iloc[:,4], errors="coerce"),
                    "volume": pd.to_numeric(df_raw.iloc[:,5], errors="coerce"),
                }).dropna()
                if len(df) > 0:
                    return df
        except Exception:
            pass
        time.sleep(0.25)
    return None

def fetch_binance_data(interval="5m", limit=200, retries=1):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": "BTCUSDT", "interval": interval, "limit": min(int(limit),1000)}
    headers = {"User-Agent": "Mozilla/5.0 SpiralBot"}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            LAST_FETCH_DEBUG["binance"] = f"BINANCE {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            arr = _safe_json(r)
            if isinstance(arr, list) and arr:
                df_raw = pd.DataFrame(arr)
                df = pd.DataFrame({
                    "time":   pd.to_numeric(df_raw.iloc[:,6], errors="coerce").astype("int64"),
                    "open":   pd.to_numeric(df_raw.iloc[:,1], errors="coerce"),
                    "high":   pd.to_numeric(df_raw.iloc[:,2], errors="coerce"),
                    "low":    pd.to_numeric(df_raw.iloc[:,3], errors="coerce"),
                    "close":  pd.to_numeric(df_raw.iloc[:,4], errors="coerce"),
                    "volume": pd.to_numeric(df_raw.iloc[:,5], errors="coerce"),
                }).dropna()
                if len(df) > 0:
                    return df
        except Exception:
            pass
        time.sleep(0.25)
    return None

def fetch_bybit_data(interval="5", limit=200, retries=1):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category":"linear","symbol":"BTCUSDT","interval":interval,"limit":min(int(limit),200)}
    headers = {
        "User-Agent": "Mozilla/5.0 SpiralBot",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.bybit.com", "Referer": "https://www.bybit.com/",
    }
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10, allow_redirects=True)
            LAST_FETCH_DEBUG["bybit"] = f"BYBIT {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            j = _safe_json(r)
            if j and j.get("result",{}).get("list"):
                df_raw = pd.DataFrame(j["result"]["list"])
                df = pd.DataFrame({
                    "time":   pd.to_numeric(df_raw.iloc[:,0], errors="coerce").astype("int64"),
                    "open":   pd.to_numeric(df_raw.iloc[:,1], errors="coerce"),
                    "high":   pd.to_numeric(df_raw.iloc[:,2], errors="coerce"),
                    "low":    pd.to_numeric(df_raw.iloc[:,3], errors="coerce"),
                    "close":  pd.to_numeric(df_raw.iloc[:,4], errors="coerce"),
                    "volume": pd.to_numeric(df_raw.iloc[:,5], errors="coerce"),
                }).dropna()
                if len(df) > 0:
                    return df
        except Exception:
            pass
        time.sleep(0.25)
    return None

def _get_live_df(interval="5m", limit=200):
    df = fetch_mexc_data(interval=interval, limit=limit); src = "MEXC"
    if df is None:
        df = fetch_okx_data(interval=interval, limit=limit); src = "OKX"
    if df is None:
        df = fetch_binance_data(interval=interval, limit=limit); src = "BINANCE"
    if df is None:
        df = fetch_bybit_data(interval="5", limit=limit); src = "BYBIT"
    return df, src

def check_data_source():
    try:
        if fetch_mexc_data(limit=2) is not None: return "✅ Connected to MEXC"
    except Exception: pass
    try:
        if fetch_okx_data(limit=2) is not None: return "✅ Connected to OKX"
    except Exception: pass
    try:
        if fetch_binance_data(limit=2) is not None: return "✅ Connected to BINANCE"
    except Exception: pass
    try:
        if fetch_bybit_data(limit=2) is not None: return "✅ Connected to BYBIT"
    except Exception: pass
    return "❌ Failed to connect to MEXC/OKX/BINANCE/BYBIT.\n\nDiag:\n" + quick_diag()

# -------- indicators & signals ----------
def calculate_vwap(df):
    cum_q = (df["close"] * df["volume"]).cumsum()
    cum_v = df["volume"].cumsum().replace(0, np.nan)
    return (cum_q / cum_v).fillna(df["close"])

def calculate_ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    d = series.diff()
    up = d.clip(lower=0)
    dn = (-d.clip(upper=0))
    ma_up = up.rolling(period).mean()
    ma_dn = dn.rolling(period).mean().replace(0, np.nan)
    rs = ma_up / ma_dn
    return (100 - (100 / (1 + rs))).fillna(50)

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

# Loosened rules (kept from your working build)
def detect_signal(df):
    latest = df.iloc[-1]
    prev   = df.iloc[-2]

    rsi_ok_long  = latest["rsi"] > 48
    rsi_ok_short = latest["rsi"] < 52

    engulf_long_ok  = (latest.get("engulfing") == "bullish")
    engulf_short_ok = (latest.get("engulfing") == "bearish")

    strong_rsi_long  = latest["rsi"] > 55
    strong_rsi_short = latest["rsi"] < 45

    cross_or_continue_long  = (prev["ema_fast"] <= prev["ema_slow"]) or (latest["ema_fast"] > latest["ema_slow"])
    cross_or_continue_short = (prev["ema_fast"] >= prev["ema_slow"]) or (latest["ema_fast"] < latest["ema_slow"])

    long_ok = (
        latest["ema_fast"] > latest["ema_slow"] and
        latest["close"] > latest["vwap"] and
        (engulf_long_ok or strong_rsi_long) and
        rsi_ok_long and
        cross_or_continue_long
    )
    short_ok = (
        latest["ema_fast"] < latest["ema_slow"] and
        latest["close"] < latest["vwap"] and
        (engulf_short_ok or strong_rsi_short) and
        rsi_ok_short and
        cross_or_continue_short
    )

    if long_ok:  return "long"
    if short_ok: return "short"
    return None

# -------- scanner & backtest ----------
def scan_market():
    df, source = _get_live_df(interval="5m", limit=200)
    if df is None or len(df) < 30:
        return None, f"❌ Data Error:\nNo data from MEXC/OKX/BINANCE/BYBIT.\n\nDiag:\n{quick_diag()}\nTry /forcescan again."

    df = _compute_indicators(df)
    sig = detect_signal(df)
    price = float(df.iloc[-1]["close"])
    rsi   = float(df.iloc[-1]["rsi"])
    vwap  = float(df.iloc[-1]["vwap"])
    ema_fast = float(df.iloc[-1]["ema_fast"])
    ema_slow = float(df.iloc[-1]["ema_slow"])
    engulf = df.iloc[-1]["engulfing"]

    if sig:
        sl  = price - 300 if sig == "long" else price + 300
        tp1 = price + 600 if sig == "long" else price - 600
        tp2 = price + 1500 if sig == "long" else price - 1500
        score = 2.5  # placeholder

        save_trade({
            "time": now_local().strftime('%Y-%m-%d %H:%M %Z'),
            "signal": sig,
            "entry": price,
            "sl": sl, "tp1": tp1, "tp2": tp2,
            "rsi": rsi, "vwap": vwap,
            "ema_fast": ema_fast, "ema_slow": ema_slow,
            "engulf": engulf, "score": score,
            "source": source, "result": ""
        })

        title = f"🚨 {sig.upper()} Signal ({source})"
        body  = (
            f"Entry: {round(price)}\n"
            f"RSI: {rsi:.1f} | VWAP: {'Bull' if price>vwap else 'Bear'} | "
            f"EMA9{'>' if ema_fast>ema_slow else '<'}EMA21 | Engulfing: {engulf}\n"
            f"TP1: {round(tp1)} (+$600) | TP2: {round(tp2)} (+$1500)\n"
            f"SL: {round(sl)} (-$300)\n"
            f"Confidence: {score}/3.0\n"
            f"Time: {now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        )
        return title, body

    return None, f"No signal at the moment. ({source})"

def run_backtest_stream(days=2):
    df, source = _get_live_df(interval="5m", limit=500)
    if df is None or len(df) < 50:
        return [f"❌ Backtest: unable to fetch history from MEXC/OKX/BINANCE/BYBIT."]
    df = _compute_indicators(df)

    lines, active = [], None
    for i in range(2, len(df)):
        row = df.iloc[i]
        price = float(row["close"])

        if active:
            if active["dir"] == "long":
                if price >= active["tp2"]:
                    lines.append(f"✅ TP2 hit @ {round(price)} (+$1500) [{source}]"); active=None
                elif price >= active["tp1"]:
                    lines.append(f"✅ TP1 hit @ {round(price)} (+$600) – holding for TP2 [{source}]")
                elif price <= active["sl"]:
                    lines.append(f"❌ SL hit @ {round(price)} (-$300) [{source}]"); active=None
            else:
                if price <= active["tp2"]:
                    lines.append(f"✅ TP2 hit @ {round(price)} (+$1500) [{source}]"); active=None
                elif price <= active["tp1"]:
                    lines.append(f"✅ TP1 hit @ {round(price)} (+$600) – holding for TP2 [{source}]")
                elif price >= active["sl"]:
                    lines.append(f"❌ SL hit @ {round(price)} (-$300) [{source}]"); active=None

        if not active:
            seg = df.iloc[: i+1]
            sig = detect_signal(seg)
            if sig in ("long","short"):
                entry = price
                sl  = entry - 300 if sig == "long" else entry + 300
                tp1 = entry + 600 if sig == "long" else entry - 600
                tp2 = entry + 1500 if sig == "long" else entry - 1500
                active = {"dir": sig, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2}
                lines.append(
                    f"{'🟢 LONG' if sig=='long' else '🔴 SHORT'} entry @ {round(entry)} | "
                    f"SL {round(sl)} TP {round(tp1)}→{round(tp2)} [{source}]"
                )

    return lines or ["(Backtest finished: no qualifying entries)"]
