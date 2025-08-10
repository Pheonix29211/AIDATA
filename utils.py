# utils.py
import os, json, math, time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np

# ====== CONFIG ======
SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()
TZ = os.getenv("TZ", "Asia/Kolkata")
TRADE_LOG = os.getenv("TRADE_LOG_FILE", "trade_logs.json")

# Risk/Target (dollars)
SL_CAP_BASE = float(os.getenv("SL_CAP_BASE", "300"))
TP1_DOLLARS = float(os.getenv("TP1_DOLLARS", "600"))
TP2_DOLLARS = float(os.getenv("TP2_DOLLARS", "1500"))

# Filters (tweak via env if needed)
RSI_MIN = float(os.getenv("RSI_MIN", "32"))
RSI_MAX = float(os.getenv("RSI_MAX", "68"))
ENGULF_LOOKBACK = int(os.getenv("ENGULF_LOOKBACK", "3"))
AI_MIN = float(os.getenv("AI_MIN", "0.0"))  # set >0.0 if you want to gate by AI
ENABLE_BREAKOUT = os.getenv("ENABLE_BREAKOUT", "false").lower() == "true"
ENABLE_PULLBACK = os.getenv("ENABLE_PULLBACK", "false").lower() == "true"

# ====== AI CORE HOOKS ======
try:
    from ai_core import score as ai_score, online_update, register_outcome
except Exception:
    def ai_score(features, regime): return (0.50, 0.05)
    def online_update(features, regime, reward): pass
    def register_outcome(outcome): pass

LAST_AI_SCORE = None
LAST_AI_EXPLORE = None
LAST_REGIME = "?"

# ====== LOG FILE HELPERS ======
def _ensure_log_file():
    if not os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, "w") as f:
            f.write("[]")

def _load_logs():
    _ensure_log_file()
    try:
        with open(TRADE_LOG, "r") as f:
            return json.load(f)
    except Exception:
        with open(TRADE_LOG, "w") as f:
            f.write("[]")
        return []

def _save_logs(logs):
    with open(TRADE_LOG, "w") as f:
        json.dump(logs, f, indent=2)

# ====== INDICATORS ======
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = df["close"].ewm(span=20).mean()
    df["ema_slow"] = df["close"].ewm(span=50).mean()
    # RSI 14
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0.0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean().replace(0, np.nan)
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(50)
    # VWAP (running)
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].replace(0, np.nan).cumsum()
    # Engulfing
    df["bull_engulf"] = (df["close"] > df["open"]) & (df["open"].shift(1) > df["close"].shift(1)) & (df["close"] > df["open"].shift(1)) & (df["open"] < df["close"].shift(1))
    df["bear_engulf"] = (df["close"] < df["open"]) & (df["open"].shift(1) < df["close"].shift(1)) & (df["close"] < df["open"].shift(1)) & (df["open"] > df["close"].shift(1))
    return df

# ====== AI GAUGE ======
def _compute_ai_gauge(df: pd.DataFrame):
    global LAST_AI_SCORE, LAST_AI_EXPLORE, LAST_REGIME
    last = df.iloc[-1]
    ema_fast = df["ema_fast"].iloc[-1]
    ema_slow = df["ema_slow"].iloc[-1]
    vwap = df["vwap"].iloc[-1]
    if ema_fast > ema_slow and last["close"] > vwap:
        regime = "trend"
    elif ema_fast < ema_slow and last["close"] < vwap:
        regime = "trend"
    else:
        regime = "range"
    ema_spread = float((ema_fast - ema_slow) / max(1e-9, abs(ema_slow)))
    ema_slope = float(df["ema_fast"].iloc[-1] - df["ema_fast"].iloc[-5]) if len(df) >= 6 else 0.0
    p, explore = ai_score({"ema_spread": ema_spread, "ema_slope": ema_slope}, regime)
    LAST_AI_SCORE = float(p); LAST_AI_EXPLORE = float(explore); LAST_REGIME = regime
    return p, explore, regime

def get_ai_status():
    if LAST_AI_SCORE is None:
        return "🤖 AI: no reading yet."
    return f"🤖 AI score {LAST_AI_SCORE:.2f} | explore {LAST_AI_EXPLORE:.2f} | regime {LAST_REGIME}"

# ====== MEXC (old working v3) ======
_MEXC_V3_MAIN = "https://api.mexc.com/api/v3/klines"
_MEXC_V3_ALT  = "https://www.mexc.com/api/v3/klines"  # sometimes HTML
_VALID_TF = {"1m","5m","15m","30m","1h","4h","1d"}
_last_mexc_diag = {"status": None, "endpoint": None, "preview": None}

def _mexc_raw(symbol: str, interval: str, limit: int = 500):
    params = {"symbol": symbol, "interval": interval, "limit": min(1000, int(limit))}
    for url in (_MEXC_V3_MAIN, _MEXC_V3_ALT):
        try:
            r = requests.get(url, params=params, timeout=10)
            try:
                data = r.json()
                _last_mexc_diag.update({"status": r.status_code, "endpoint": url, "preview": "JSON ok"})
                return r.status_code, data
            except Exception:
                _last_mexc_diag.update({"status": r.status_code, "endpoint": url, "preview": (r.text[:250] if r.text else "no text")})
                return r.status_code, None
        except Exception as e:
            _last_mexc_diag.update({"status": 0, "endpoint": url, "preview": f"{type(e).__name__}: {e}"})
            continue
    return 0, None

def fetch_mexc(tf: str = "5m", limit: int = 500):
    tf = tf.strip().lower()
    if tf not in _VALID_TF: return None
    status, payload = _mexc_raw(SYMBOL, tf, limit)
    if status == 200 and isinstance(payload, list) and payload and isinstance(payload[0], (list, tuple)):
        rows = []
        for k in payload:
            try:
                rows.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
            except Exception:
                continue
        if not rows: return None
        df = pd.DataFrame(rows, columns=["open_time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(TZ)
        df.set_index("time", inplace=True)
        return df[["open","high","low","close","volume"]]
    return None

# Optional Bybit fallback (kept minimal; not required if MEXC is fine)
def fetch_bybit(tf: str = "5m", limit: int = 500):
    tfmap = {"1m":"1","5m":"5","15m":"15","30m":"30","1h":"60"}
    if tf not in tfmap: return None
    try:
        url = "https://api.bybit.com/v5/market/kline"
        params = {"category":"linear", "symbol": SYMBOL, "interval": tfmap[tf], "limit": min(limit, 1000)}
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("retCode") != 0: return None
        kl = data["result"]["list"]
        rows = []
        for k in kl[::-1]:
            rows.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])])
        df = pd.DataFrame(rows, columns=["open_time","open","high","low","close","volume"])
        df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(TZ)
        df.set_index("time", inplace=True)
        return df[["open","high","low","close","volume"]]
    except Exception:
        return None

def diag_data():
    out = ["📡 MEXC diag"]
    for tf in ["1m","5m","15m","30m","1h"]:
        df = fetch_mexc(tf, limit=200)
        if df is None:
            s = _last_mexc_diag.get("status"); ep = _last_mexc_diag.get("endpoint"); pv = _last_mexc_diag.get("preview")
            out.append(f"{tf}: None | {s} | {ep} | {pv}")
        else:
            out.append(f"{tf}: {len(df)} bars, last={df.index[-1]}")
    return "\n".join(out)

# ====== SIGNAL BUILDING ======
def _fmt(x: float) -> str:
    return f"{x:,.2f}"

def _build_signal(side: str, px: float):
    if side == "LONG":
        sl = px - SL_CAP_BASE
        tp1 = px + TP1_DOLLARS
        tp2 = px + TP2_DOLLARS
        return (f"🟢 LONG @ { _fmt(px) } | SL { _fmt(sl) } "
                f"TP { _fmt(tp1) }→{ _fmt(tp2) } [MEXC]"), sl, tp1, tp2
    else:
        sl = px + SL_CAP_BASE
        tp1 = px - TP1_DOLLARS
        tp2 = px - TP2_DOLLARS
        return (f"🔴 SHORT @ { _fmt(px) } | SL { _fmt(sl) } "
                f"TP { _fmt(tp1) }→{ _fmt(tp2) } [MEXC]"), sl, tp1, tp2

def record_trade(entry: dict):
    logs = _load_logs()
    logs.append(entry)
    _save_logs(logs)

def get_trade_logs():
    logs = _load_logs()
    if not logs:
        return "🧾 No trades logged yet."
    tail = logs[-30:]
    lines = []
    for t in tail:
        lines.append(
            f"{t.get('t','')} | {t.get('tf','')} | {t.get('side','')} @ {t.get('px','')} "
            f"SL {t.get('sl','')} TP {t.get('tp1','')}→{t.get('tp2','')} "
            f"AI {t.get('ai',0):.2f}"
        )
    return "🧾 Last trades:\n" + "\n".join(lines)

def get_results():
    logs = _load_logs()
    if not logs:
        return "📈 No results yet."
    wins = sum(1 for t in logs if t.get("outcome") in ("TP1","TP2"))
    tp2  = sum(1 for t in logs if t.get("outcome") == "TP2")
    sls  = sum(1 for t in logs if t.get("outcome") == "SL")
    open_count = sum(1 for t in logs if t.get("outcome") == "OPEN")
    return f"📈 Results: wins {wins}, TP2 {tp2}, SL {sls}, open {open_count} (total {len(logs)})"

def get_bot_status():
    return (
        "📊 Current Logic:\n"
        f"- {SYMBOL} on MEXC (v3)\n"
        f"- VWAP/EMA cross (5m)\n"
        f"- RSI {RSI_MIN:.0f}–{RSI_MAX:.0f} + Engulfing (lookback {ENGULF_LOOKBACK})\n"
        f"- ${SL_CAP_BASE:.0f} SL, ${TP1_DOLLARS:.0f}–${TP2_DOLLARS:.0f} TP\n"
        f"- Breakout {ENABLE_BREAKOUT}, Pullback {ENABLE_PULLBACK}\n"
    )

# ====== SCAN ======
def scan_market():
    # 5m TF by default
    df = fetch_mexc("5m", limit=600)
    if df is None or len(df) < 60:
        df = fetch_bybit("5m", limit=600)
    if df is None or len(df) < 60:
        return ("❌ Data Error:", "No 5m data from MEXC or Bybit. Try /diag then /forcescan.")

    # build indicators + AI
    df = compute_indicators(df)
    p, explore, regime = _compute_ai_gauge(df)

    last = df.iloc[-1]
    trend_up = (last["ema_fast"] > last["ema_slow"]) and (last["close"] > last["vwap"])
    trend_dn = (last["ema_fast"] < last["ema_slow"]) and (last["close"] < last["vwap"])

    bull_recent = df["bull_engulf"].rolling(ENGULF_LOOKBACK).max().iloc[-2]
    bear_recent = df["bear_engulf"].rolling(ENGULF_LOOKBACK).max().iloc[-2]

    long_base  = trend_up and (last["rsi"] <= RSI_MAX) and bool(bull_recent)
    short_base = trend_dn and (last["rsi"] >= RSI_MIN) and bool(bear_recent)

    breakout_long = breakout_short = False
    if ENABLE_BREAKOUT:
        swing_hi = df["high"].rolling(20).max().iloc[-2]
        swing_lo = df["low"].rolling(20).min().iloc[-2]
        vol_up = last["volume"] > df["volume"].rolling(20).mean().iloc[-1]
        breakout_long = trend_up and last["close"] > swing_hi and vol_up
        breakout_short = trend_dn and last["close"] < swing_lo and vol_up

    pullback_long = pullback_short = False
    if ENABLE_PULLBACK:
        ema20_prev = df["close"].ewm(span=20).mean().iloc[-2]
        pullback_long = trend_up and (df["low"].iloc[-2] <= ema20_prev <= df["high"].iloc[-2]) and (last["close"] > ema20_prev)
        pullback_short = trend_dn and (df["low"].iloc[-2] <= ema20_prev <= df["high"].iloc[-2]) and (last["close"] < ema20_prev)

    long_ok  = long_base  or breakout_long  or pullback_long
    short_ok = short_base or breakout_short or pullback_short

    # Optional AI gating
    if AI_MIN > 0.0:
        if long_ok and p < AI_MIN:  long_ok = False
        if short_ok and p < AI_MIN: short_ok = False

    # No-trade path
    if not (long_ok ^ short_ok):
        head = "ℹ️ No trade"
        details = f"TF 5m | Regime {regime} | AI {p:.2f}"
        return head, details

    side = "LONG" if long_ok else "SHORT"
    head, sl, tp1, tp2 = _build_signal(side, float(last["close"]))
    details = (
        f"TF 5m | EMA{'↑' if trend_up else '↓'} VWAP{'↑' if trend_up else '↓'} "
        f"| RSI {last['rsi']:.1f} | Regime {regime} | AI {p:.2f}"
    )

    # Log the signal (as OPEN idea)
    record_trade({
        "t": datetime.now(timezone.utc).isoformat(),
        "tf": "5m",
        "side": side,
        "px": float(last["close"]),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "ai": float(p),
        "outcome": "OPEN"
    })
    return head, details

# ====== BACKTEST (2–7 days, 5m) ======
def run_backtest(days: int = 2):
    bars_needed = int((days * 24 * 60) / 5) + 50  # add buffer
    df = fetch_mexc("5m", limit=min(1000, bars_needed))
    if df is None or len(df) < 120:
        return ("❌ Backtest", "unable to fetch history from MEXC.")

    df = compute_indicators(df)
    entries = []
    wins = tp2s = sls = 0
    lines = []

    for i in range(60, len(df) - 1):
        window = df.iloc[:i+1]
        last = window.iloc[-1]
        p, _, regime = _compute_ai_gauge(window)

        trend_up = (last["ema_fast"] > last["ema_slow"]) and (last["close"] > last["vwap"])
        trend_dn = (last["ema_fast"] < last["ema_slow"]) and (last["close"] < last["vwap"])
        bull_recent = window["bull_engulf"].rolling(ENGULF_LOOKBACK).max().iloc[-2]
        bear_recent = window["bear_engulf"].rolling(ENGULF_LOOKBACK).max().iloc[-2]
        long_ok  = trend_up and (last["rsi"] <= RSI_MAX) and bool(bull_recent)
        short_ok = trend_dn and (last["rsi"] >= RSI_MIN) and bool(bear_recent)

        # AI gate if enabled
        if AI_MIN > 0.0:
            if long_ok and p < AI_MIN:  long_ok = False
            if short_ok and p < AI_MIN: short_ok = False

        if not (long_ok ^ short_ok):
            continue

        side = "LONG" if long_ok else "SHORT"
        entry = float(last["close"])
        sl = entry - SL_CAP_BASE if side == "LONG" else entry + SL_CAP_BASE
        tp1 = entry + TP1_DOLLARS if side == "LONG" else entry - TP1_DOLLARS
        tp2 = entry + TP2_DOLLARS if side == "LONG" else entry - TP2_DOLLARS

        # Walk forward up to next 288 bars (~1 day) or until hit
        outcome = "OPEN"
        for j in range(i+1, min(i+1+288, len(df))):
            bar = df.iloc[j]
            hi, lo = float(bar["high"]), float(bar["low"])
            if side == "LONG":
                if hi >= tp2:
                    outcome = "TP2"; tp2s += 1; wins += 1; break
                if hi >= tp1:
                    outcome = "TP1"; wins += 1; break
                if lo <= sl:
                    outcome = "SL";  sls  += 1; break
            else:
                if lo <= tp2:
                    outcome = "TP2"; tp2s += 1; wins += 1; break
                if lo <= tp1:
                    outcome = "TP1"; wins += 1; break
                if hi >= sl:
                    outcome = "SL";  sls  += 1; break

        entries.append((window.index[-1], side, entry, outcome))
        if len(lines) < 80:  # avoid Telegram overflow
            lines.append(f"{window.index[-1]} | {side} @ {entry:,.2f} → {outcome}")

    total = len(entries)
    head = f"🧪 Backtest ({days}d, 5m): {total} entries | Wins {wins} | TP2 {tp2s} | SL {sls}"
    details = "\n".join(lines) if lines else "(no qualifying entries)"
    return head, details
