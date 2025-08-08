import os
import json
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------- Files / State ----------------
TRADE_LOG_FILE = "trade_logs.json"
STATE_FILE = "trade_state.json"
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 SpiralBot"}
LAST_FETCH_DEBUG = {"mexc":"", "okx":"", "binance":"", "bybit":""}

def now_local():
    tz = os.getenv("TIMEZONE", "Asia/Kolkata")
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        return datetime.utcnow()

def _ensure_file_json(path, default_obj):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default_obj, f)

def _load_state():
    _ensure_file_json(STATE_FILE, {"active": None, "cooloff_until": 0})
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"active": None, "cooloff_until": 0}

def _save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)

STATE = _load_state()

# ---------------- Logs ----------------
def quick_diag():
    return (
        f"MEXC: {LAST_FETCH_DEBUG.get('mexc','no call yet')}\n"
        f"OKX: {LAST_FETCH_DEBUG.get('okx','no call yet')}\n"
        f"BINANCE: {LAST_FETCH_DEBUG.get('binance','no call yet')}\n"
        f"BYBIT: {LAST_FETCH_DEBUG.get('bybit','no call yet')}"
    )

def _ensure_trade_log():
    _ensure_file_json(TRADE_LOG_FILE, [])

def load_trades():
    _ensure_trade_log()
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

# ------------- Data Fetchers (MEXC → OKX → BINANCE → BYBIT) -------------
def _safe_json(resp):
    txt = (resp.text or "").strip()
    if not txt:
        return None
    try:
        return resp.json()
    except Exception:
        return None

def fetch_mexc(interval="5m", limit=200, retries=2):
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol":"BTCUSDT","interval":interval,"limit":min(int(limit),1000)}
    headers = {"User-Agent":"Mozilla/5.0 SpiralBot","Accept":"application/json"}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            LAST_FETCH_DEBUG["mexc"] = f"v3 {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
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
                if len(df)>0: return df
        except Exception:
            pass
        time.sleep(0.2)
    return None

def fetch_okx(interval="5m", limit=200, retries=2):
    bar_map = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","60m":"1H"}
    url = "https://www.okx.com/api/v5/market/candles"
    params = {"instId":"BTC-USDT","bar":bar_map.get(interval,"5m"),"limit":min(int(limit),300)}
    headers = {"User-Agent":"Mozilla/5.0 SpiralBot","Accept":"application/json"}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            LAST_FETCH_DEBUG["okx"] = f"OKX {r.status_code} | {(r.text or '')[:120].replace(chr(10),' ')}"
            j = _safe_json(r)
            if j and j.get("code")=="0" and j.get("data"):
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
                if len(df)>0: return df
        except Exception:
            pass
        time.sleep(0.2)
    return None

def fetch_binance(interval="5m", limit=200, retries=1):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol":"BTCUSDT","interval":interval,"limit":min(int(limit),1000)}
    headers = {"User-Agent":"Mozilla/5.0 SpiralBot"}
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
                if len(df)>0: return df
        except Exception:
            pass
        time.sleep(0.2)
    return None

def fetch_bybit(interval="5", limit=200, retries=1):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category":"linear","symbol":"BTCUSDT","interval":interval,"limit":min(int(limit),200)}
    headers = {"User-Agent":"Mozilla/5.0 SpiralBot","Accept":"application/json"}
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
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
                if len(df)>0: return df
        except Exception:
            pass
        time.sleep(0.2)
    return None

def _get_df(interval="5m", limit=200):
    df = fetch_mexc(interval, limit); src = "MEXC"
    if df is None: df, src = fetch_okx(interval, limit), "OKX"
    if df is None: df, src = fetch_binance(interval, limit), "BINANCE"
    if df is None:
        if interval == "1m":
            df, src = fetch_bybit("1", limit), "BYBIT"
        else:
            df, src = fetch_bybit("5", limit), "BYBIT"
    return df, src

def check_data_source():
    for fn, lab in [(fetch_mexc,"MEXC"),(fetch_okx,"OKX"),(fetch_binance,"BINANCE")]:
        try:
            if fn(limit=2) is not None: return f"✅ Connected to {lab}"
        except Exception: pass
    try:
        if fetch_bybit(limit=2) is not None: return "✅ Connected to BYBIT"
    except Exception: pass
    return "❌ Failed to connect to MEXC/OKX/BINANCE/BYBIT.\n\nDiag:\n" + quick_diag()

# ---------------- Indicators ----------------
def calculate_vwap(df):
    q = df["close"] * df["volume"]
    return (q.cumsum() / df["volume"].replace(0,np.nan).cumsum()).fillna(df["close"])

def calculate_ema(df, period):
    return df["close"].ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    d = series.diff()
    up = d.clip(lower=0); dn = (-d.clip(upper=0))
    ma_up = up.rolling(period).mean()
    ma_dn = dn.rolling(period).mean().replace(0, np.nan)
    rs = ma_up / ma_dn
    return (100 - (100 / (1 + rs))).fillna(50)

def calculate_atr(df, period=14):
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def detect_engulfing(df):
    out = [None]
    for i in range(1, len(df)):
        o1,c1 = df["open"].iloc[i-1], df["close"].iloc[i-1]
        o2,c2 = df["open"].iloc[i],   df["close"].iloc[i]
        prev_body = abs(c1 - o1); curr_body = abs(c2 - o2)
        bull = (c2>o2) and (o2<c1) and (c2>o1) and (curr_body > prev_body)
        bear = (c2<o2) and (o2>c1) and (c2<o1) and (curr_body > prev_body)
        out.append("bullish" if bull else "bearish" if bear else None)
    return out

def _compute_indicators(df):
    df = df.copy()
    df["ema_fast"] = calculate_ema(df, 9)
    df["ema_slow"] = calculate_ema(df, 21)
    df["vwap"] = calculate_vwap(df)
    df["rsi"] = calculate_rsi(df["close"], 14)
    df["atr"] = calculate_atr(df, 14)
    df["engulfing"] = detect_engulfing(df)
    return df

# ---------------- Entry (15m + 5m only) ----------------
def _dir_row(z):
    long_ok  = (z["close"] > z["vwap"]) and (z["ema_fast"] > z["ema_slow"]) and (z["rsi"] > 50)
    short_ok = (z["close"] < z["vwap"]) and (z["ema_fast"] < z["ema_slow"]) and (z["rsi"] < 50)
    if long_ok: return "long"
    if short_ok: return "short"
    return None

def _score_entry(z5, z15, dir5, dir15):
    if dir5 is None or dir15 is None or dir5 != dir15:
        return 0.6
    score = 2.0
    if z5.get("engulfing") in ["bullish", "bearish"]:
        score += 0.4
    if (dir5 == "long" and z5["rsi"] > 55) or (dir5 == "short" and z5["rsi"] < 45):
        score += 0.3
    body = abs(z5["close"] - z5["open"])
    atr5 = float(z5["atr"]) or 1.0
    if (body / atr5) < 0.3:
        score -= 0.6
    return max(0.0, min(3.0, score))

def _get_df_pair_for_entry():
    df15, src15 = _get_df("15m", limit=220)
    df5,  src5  = _get_df("5m",  limit=220)
    return df15, df5, src15, src5

def scan_market():
    # one-trade lock
    if STATE.get("active"):
        return None, "In trade — waiting for TP/SL. (No duplicate entries)"

    # cool-off after SL
    if time.time() < STATE.get("cooloff_until", 0):
        left = int(STATE["cooloff_until"] - time.time())
        return None, f"⏳ Cool-off {left}s after SL."

    df15, df5, src15, src5 = _get_df_pair_for_entry()
    if df15 is None or len(df15) < 60 or df5 is None or len(df5) < 60:
        return None, f"❌ Data Error:\nNo data from providers.\n\nDiag:\n{quick_diag()}"

    df15 = _compute_indicators(df15)
    df5  = _compute_indicators(df5)

    z15 = df15.iloc[-1]
    z5  = df5.iloc[-1]

    # Chop filter on 5m
    price = float(z5["close"])
    atr_pct = float(z5["atr"]) / max(price, 1.0)
    min_atr_pct = float(os.getenv("MIN_ATR_PCT", "0.0015"))  # 0.15%
    if atr_pct < min_atr_pct:
        return None, f"ℹ️ No trade: chop (ATR {atr_pct:.3%} < {min_atr_pct:.3%})."

    # Direction on each TF
    dir15 = _dir_row(z15)
    dir5  = _dir_row(z5)
    if dir15 is None or dir5 is None or dir15 != dir5:
        return None, f"ℹ️ No trade: TF mismatch (15m {dir15}, 5m {dir5})."

    # Score
    score = _score_entry(z5, z15, dir5, dir15)
    if score < 2.0:
        return None, f"ℹ️ No trade: score too low ({score:.2f}/3)."

    # Build levels
    sig = dir5
    sl  = price - 300 if sig == "long" else price + 300
    tp1 = price + 600 if sig == "long" else price - 600
    tp2 = price + 1500 if sig == "long" else price - 1500

    save_trade({
        "time": now_local().strftime('%Y-%m-%d %H:%M %Z'),
        "signal": sig, "entry": price,
        "sl": sl, "tp1": tp1, "tp2": tp2,
        "rsi": float(z5["rsi"]),
        "vwap": float(z5["vwap"]),
        "ema_fast": float(z5["ema_fast"]),
        "ema_slow": float(z5["ema_slow"]),
        "engulf": z5["engulfing"],
        "score": round(score, 2),
        "source": f"15m:{src15} + 5m:{src5}",
        "result": ""
    })

    STATE["active"] = {
        "dir": sig, "entry": price, "sl": sl, "tp1": tp1, "tp2": tp2,
        "source": f"15m:{src15} + 5m:{src5}",
        "sent_tp1": False,
        "last_hold_ts": 0,
        "last_slwarn_ts": 0,
        "last_weak_ts": 0
    }
    STATE["active_meta"] = {"bars_since_entry": 0}
    _save_state(STATE)

    title = f"🚨 {sig.upper()} Signal (15m+5m agree)"
    body  = (
        f"Entry: {round(price)} | Score: {score:.2f}/3.0\n"
        f"5m: RSI {z5['rsi']:.1f}, EMA9{'>' if z5['ema_fast']>z5['ema_slow'] else '<'}EMA21, "
        f"{'Above' if z5['close']>z5['vwap'] else 'Below'} VWAP, Engulf: {z5['engulfing']}\n"
        f"15m: RSI {z15['rsi']:.1f}, EMA9{'>' if z15['ema_fast']>z15['ema_slow'] else '<'}EMA21, "
        f"{'Above' if z15['close']>z15['vwap'] else 'Below'} VWAP\n"
        f"TP1: {round(tp1)} (+$600) | TP2: {round(tp2)} (+$1500) | SL: {round(sl)} (-$300)\n"
        f"{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
    )
    return title, body

# ---------------- Momentum pings (1m + 5m context) ----------------
def _get_df_for_momentum():
    df5, src5 = _get_df("5m", limit=80)
    df1, src1 = _get_df("1m", limit=160)
    return df5, df1, src5, src1

def momentum_tick():
    if not STATE.get("active"):
        return None, None

    active = STATE["active"]
    df5, df1, src5, src1 = _get_df_for_momentum()
    if df5 is None or len(df5)<20 or df1 is None or len(df1)<40:
        return None, None

    df5 = _compute_indicators(df5)
    df1 = _compute_indicators(df1)
    z5 = df5.iloc[-1]; z1 = df1.iloc[-1]

    price = float(z5["close"])
    v5, e5f, e5s, r5 = float(z5["vwap"]), float(z5["ema_fast"]), float(z5["ema_slow"]), float(z5["rsi"])
    v1, e1f, e1s, r1 = float(z1["vwap"]), float(z1["ema_fast"]), float(z1["ema_slow"]), float(z1["rsi"])
    nowts = time.time()

    # TP/SL one-shot logic
    if active["dir"] == "long":
        if price >= active["tp2"]:
            STATE["active"] = None; _save_state(STATE)
            return "🎯 Take Profit 2", f"✅ TP2 @ {round(price)} (+$1500)\nClosed.\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        if price >= active["tp1"] and not active.get("sent_tp1", False):
            active["sent_tp1"] = True; _save_state(STATE)
            return "✅ TP1 Reached", f"TP1 @ {round(price)} (+$600) — holding for TP2.\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        if price <= active["sl"]:
            STATE["cooloff_until"] = nowts + int(os.getenv("COOLOFF_AFTER_SL_SEC","600"))
            STATE["active"] = None; _save_state(STATE)
            return "🛑 Stop Loss", f"SL @ {round(price)} (-$300). Cool-off started.\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
    else:
        if price <= active["tp2"]:
            STATE["active"] = None; _save_state(STATE)
            return "🎯 Take Profit 2", f"✅ TP2 @ {round(price)} (+$1500)\nClosed.\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        if price <= active["tp1"] and not active.get("sent_tp1", False):
            active["sent_tp1"] = True; _save_state(STATE)
            return "✅ TP1 Reached", f"TP1 @ {round(price)} (+$600) — holding for TP2.\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        if price >= active["sl"]:
            STATE["cooloff_until"] = nowts + int(os.getenv("COOLOFF_AFTER_SL_SEC","600"))
            STATE["active"] = None; _save_state(STATE)
            return "🛑 Stop Loss", f"SL @ {round(price)} (-$300). Cool-off started.\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"

    # Near-SL warning (within $100)
    sl_gap = (price - active["sl"]) if active["dir"] == "long" else (active["sl"] - price)
    if sl_gap <= 100 and nowts - active.get("last_slwarn_ts", 0) > int(os.getenv("SL_WARN_COOLDOWN","180")):
        active["last_slwarn_ts"] = nowts; _save_state(STATE)
        return "⚠️ Near SL", f"Price {round(price)} near SL {round(active['sl'])} (≤$100).\n{now_local().strftime('%Y-%m-%d %H:%M %Z')}"

    # Momentum HOLD / WEAKENING checks (1m + 5m) — 1m for pings, not entries
    if active["dir"] == "long":
        hold = (price>v5 and e5f>e5s and r5>=50) and (z1["close"]>v1 and e1f>e1s and r1>=50)
        weak = (e1f<e1s or z1["close"]<v1 or r1<50)
    else:
        hold = (price<v5 and e5f<e5s and r5<=50) and (z1["close"]<v1 and e1f<e1s and r1<=50)
        weak = (e1f>e1s or z1["close"]>v1 or r1>50)

    # Throttled hold ping
    if hold and nowts - active.get("last_hold_ts", 0) > int(os.getenv("HOLD_COOLDOWN","240")):
        active["last_hold_ts"] = nowts; _save_state(STATE)
        trend = "Bullish" if active["dir"]=="long" else "Bearish"
        return "📈 Hold Momentum", (
            f"{trend} intact — HOLD.\n"
            f"5m: EMA9{'>' if e5f>e5s else '<'}EMA21, {'Above' if price>v5 else 'Below'} VWAP, RSI {r5:.1f}\n"
            f"1m: EMA9{'>' if e1f>e1s else '<'}EMA21, {'Above' if z1['close']>v1 else 'Below'} VWAP, RSI {r1:.1f}\n"
            f"{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        )

    # Throttled weakening ping
    if weak and nowts - active.get("last_weak_ts", 0) > int(os.getenv("WEAK_COOLDOWN","180")):
        active["last_weak_ts"] = nowts; _save_state(STATE)
        return "↘️ Momentum Weakening", (
            f"1m momentum fading against your {active['dir']}.\n"
            f"Price: {round(price)} | 1m RSI {r1:.1f} | 1m EMA9{'<' if active['dir']=='long' else '>'}EMA21\n"
            f"{now_local().strftime('%Y-%m-%d %H:%M %Z')}"
        )

    return None, None

# ---------------- Backtest (5m only) ----------------
def run_backtest_stream(days=2):
    df5, src5 = _get_df("5m", limit=500)
    if df5 is None or len(df5)<60:
        return ["❌ Backtest: unable to fetch history."]
    df5 = _compute_indicators(df5)

    lines, active = [], None
    for i in range(40, len(df5)):
        seg = df5.iloc[:i+1]
        z = seg.iloc[-1]; price=float(z["close"])
        long_ok  = (z["close"]>z["vwap"] and z["ema_fast"]>z["ema_slow"] and z["rsi"]>50)
        short_ok = (z["close"]<z["vwap"] and z["ema_fast"]<z["ema_slow"] and z["rsi"]<50)

        if active:
            if active["dir"]=="long":
                if price >= active["tp2"]: lines.append(f"✅ TP2 @ {round(price)}"); active=None
                elif price >= active["tp1"]: lines.append(f"✅ TP1 @ {round(price)} — holding")
                elif price <= active["sl"]: lines.append(f"❌ SL @ {round(price)}"); active=None
            else:
                if price <= active["tp2"]: lines.append(f"✅ TP2 @ {round(price)}"); active=None
                elif price <= active["tp1"]: lines.append(f"✅ TP1 @ {round(price)} — holding")
                elif price >= active["sl"]: lines.append(f"❌ SL @ {round(price)}"); active=None
            continue

            # no new entry while active (simulating one-trade lock)

        if long_ok or short_ok:
            sig = "long" if long_ok else "short"
            sl  = price - 300 if sig=="long" else price + 300
            tp1 = price + 600 if sig=="long" else price - 600
            tp2 = price + 1500 if sig=="long" else price - 1500
            active = {"dir":sig,"sl":sl,"tp1":tp1,"tp2":tp2}
            lines.append(f"{'🟢 LONG' if sig=='long' else '🔴 SHORT'} @ {round(price)} | SL {round(sl)} TP {round(tp1)}→{round(tp2)} [{src5}]")

    return lines or ["(Backtest finished: no qualifying entries)"]
