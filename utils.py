# utils.py
import os, json, time, logging, math
from datetime import datetime, timezone
from typing import Tuple, Optional

import requests
import pandas as pd
import numpy as np

# ---------------- Config ----------------
SYMBOL              = os.getenv("SYMBOL", "BTCUSDT").upper()   # MEXC spot symbol
TRADES_FILE         = os.getenv("TRADES_FILE", "trade_logs.json")

# Entry filters (Engulfing removed → trend + RSI band only)
RSI_MIN             = float(os.getenv("RSI_MIN", "30"))
RSI_MAX             = float(os.getenv("RSI_MAX", "70"))
EMA_FAST            = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW            = int(os.getenv("EMA_SLOW", "21"))

# Risk/TP in USD distance (not points)
SL_CAP_BASE         = float(os.getenv("SL_CAP_BASE", "300"))
SL_CAP_MAX          = float(os.getenv("SL_CAP_MAX", "500"))
SL_CUSHION_DOLLARS  = float(os.getenv("SL_CUSHION_DOLLARS", "50"))
TP1_DOLLARS         = float(os.getenv("TP1_DOLLARS", "600"))
TP2_DOLLARS         = float(os.getenv("TP2_DOLLARS", "1500"))

# AI gate (optional)
AI_MIN              = float(os.getenv("AI_MIN", "0.50"))

# Decision timeframe for autoscan
SCAN_TF             = os.getenv("SCAN_TF", "5m").lower()

# Valid TFs for MEXC v3
_VALID_TF = {"1m","5m","15m","30m","1h"}


# ------------- Safe JSON helpers -------------
def _load_json_safe(path: str, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read().strip()
            if not txt:
                return default
            return json.loads(txt)
    except Exception:
        return default

def _append_json_line_safe(path: str, obj: dict, max_keep: int = 2000):
    data = _load_json_safe(path, [])
    data.append(obj)
    if len(data) > max_keep:
        data = data[-max_keep:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Failed to write {path}: {e}")


# ------------- MEXC v3 data -------------
def _mexc_klines(symbol: str, tf: str = "5m", limit: int = 500):
    """
    MEXC v3 klines (public)
    GET https://api.mexc.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=500
    """
    base = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": tf, "limit": int(limit)}
    try:
        r = requests.get(base, params=params, timeout=10)
        status = r.status_code
        try:
            payload = r.json()
        except Exception:
            payload = r.text[:400]
        return status, payload
    except Exception as e:
        return 0, str(e)

def _df_from_mexc(payload) -> Optional[pd.DataFrame]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], (list,tuple)):
        return None
    arr = np.array(payload, dtype=object)
    ts  = pd.to_datetime(arr[:,0].astype(np.int64), unit="ms", utc=True).tz_convert("Asia/Kolkata")
    df = pd.DataFrame({
        "open":   pd.to_numeric(arr[:,1], errors="coerce"),
        "high":   pd.to_numeric(arr[:,2], errors="coerce"),
        "low":    pd.to_numeric(arr[:,3], errors="coerce"),
        "close":  pd.to_numeric(arr[:,4], errors="coerce"),
        "volume": pd.to_numeric(arr[:,5], errors="coerce"),
    }, index=ts)
    df = df.dropna()
    if df.empty:
        return None
    return df

def fetch_mexc(tf: str = "5m", limit: int = 500) -> Optional[pd.DataFrame]:
    tf = tf.lower().strip()
    if tf not in _VALID_TF:
        tf = "5m"
    status, payload = _mexc_klines(SYMBOL, tf, limit)
    if status == 200:
        df = _df_from_mexc(payload)
        if df is not None:
            return df
    # Hourly fallback (MEXC sometimes flaky on '1h')
    if tf == "1h":
        status2, payload2 = _mexc_klines(SYMBOL, "60m", limit)
        if status2 == 200:
            return _df_from_mexc(payload2)
    return None


# ------------- Indicators -------------
def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()

def _rsi(x: pd.Series, n: int = 14) -> pd.Series:
    delta = x.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    roll_up  = pd.Series(gain, index=x.index).ewm(alpha=1/n, adjust=False).mean()
    roll_dn  = pd.Series(loss, index=x.index).ewm(alpha=1/n, adjust=False).mean()
    rs = roll_up / (roll_dn.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def _vwap(df: pd.DataFrame, win: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].clip(lower=0.0)
    pv = (tp * vol).rolling(win).sum()
    vv = vol.rolling(win).sum().replace(0, np.nan)
    return (pv / vv).fillna(df["close"])

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["rsi"]      = _rsi(df["close"], 14)
    df["vwap"]     = _vwap(df, win=20)
    spread = (df["ema_fast"] - df["ema_slow"]).abs() / df["close"].replace(0,np.nan)
    df["regime"] = np.where(spread > 0.0009, "trend", "range")
    return df.dropna()


# ------------- Signal building (no Engulfing) -------------
def _make_signal(df: pd.DataFrame, tf: str = "5m", ai_score: float = 0.50) -> Tuple[str, str]:
    last = df.iloc[-1]
    trend_up = (last["ema_fast"] > last["ema_slow"]) and (last["close"] > last["vwap"])
    trend_dn = (last["ema_fast"] < last["ema_slow"]) and (last["close"] < last["vwap"])

    long_base  = trend_up and (RSI_MIN <= last["rsi"] <= RSI_MAX)
    short_base = trend_dn and (RSI_MIN <= last["rsi"] <= RSI_MAX)

    regime = last.get("regime","range")
    side = None
    if long_base and ai_score >= AI_MIN:
        side = "LONG"
    elif short_base and ai_score >= AI_MIN:
        side = "SHORT"

    if side is None:
        return (f"ℹ️ No trade | TF {tf} | Regime {regime} | AI {ai_score:.2f}",
                f"close={last['close']:.2f} rsi={last['rsi']:.1f} vwap={last['vwap']:.2f} emaΔ={(last['ema_fast']-last['ema_slow']):.2f}")

    price = float(last["close"])
    if side == "LONG":
        sl  = price - SL_CAP_BASE
        tp1 = price + TP1_DOLLARS
        tp2 = price + TP2_DOLLARS
    else:
        sl  = price + SL_CAP_BASE
        tp1 = price - TP1_DOLLARS
        tp2 = price - TP2_DOLLARS

    header = f"{'🟢' if side=='LONG' else '🔴'} {side} @ {price:.0f} | SL {sl:.0f} TP {tp1:.0f}→{tp2:.0f} [MEXC]"
    detail = (
        f"TF {tf} | Regime {regime} | AI {ai_score:.2f}\n"
        f"close={price:.2f}  rsi={last['rsi']:.1f}\n"
        f"vwap={last['vwap']:.2f}  ema_fast={last['ema_fast']:.2f}  ema_slow={last['ema_slow']:.2f}"
    )
    return header, detail


# ------------- Public API for bot.py -------------
def scan_market(tf: str = None) -> Tuple[str, str]:
    tf = (tf or SCAN_TF).lower()
    df = fetch_mexc(tf, limit=500)
    if df is None or len(df) < 50:
        return ("❌ Data Error:\nNo data from MEXC right now.", "fetch_mexc returned None or too few rows")
    df = compute_indicators(df)

    ai_score = 0.50
    try:
        from ai_core import score  # optional
        last = df.iloc[-1]
        features = {
            "ema_spread": float((last["ema_fast"] - last["ema_slow"]) / last["close"]),
            "ema_slope":  float((df["ema_fast"].iloc[-1] - df["ema_fast"].iloc[-5]) / 5.0 / last["close"])
        }
        ai_score, _ = score(features, regime=str(last.get("regime","range")))
    except Exception:
        pass

    return _make_signal(df, tf=tf, ai_score=ai_score)

def run_backtest(days: int = 2, tf: str = "5m") -> Tuple[str, str]:
    tf = tf.lower()
    bars_per_day = {"1m": 1440, "5m": 288, "15m": 96, "30m": 48, "1h": 24}.get(tf, 288)
    limit = min(1000, max(300, days * bars_per_day))
    df = fetch_mexc(tf, limit=limit)
    if df is None or len(df) < 60:
        return ("❌ Backtest: unable to fetch history from MEXC.", "")

    df = compute_indicators(df)
    entries = []
    for i in range(50, len(df)-1):
        row = df.iloc[i]
        trend_up = (row["ema_fast"] > row["ema_slow"]) and (row["close"] > row["vwap"])
        trend_dn = (row["ema_fast"] < row["ema_slow"]) and (row["close"] < row["vwap"])

        long_ok  = trend_up  and (RSI_MIN <= row["rsi"] <= RSI_MAX)
        short_ok = trend_dn  and (RSI_MIN <= row["rsi"] <= RSI_MAX)
        if not (long_ok or short_ok):
            continue

        side  = "LONG" if long_ok else "SHORT"
        entry = float(row["close"])
        sl    = entry - SL_CAP_BASE if side=="LONG" else entry + SL_CAP_BASE
        tp1   = entry + TP1_DOLLARS if side=="LONG" else entry - TP1_DOLLARS
        tp2   = entry + TP2_DOLLARS if side=="LONG" else entry - TP2_DOLLARS

        outcome, bars_to_exit = "OPEN", 0
        for j in range(i+1, min(i+200, len(df))):
            hi = float(df["high"].iloc[j])
            lo = float(df["low"].iloc[j])
            bars_to_exit = j - i

            if side == "LONG":
                hit_sl  = lo <= sl
                hit_tp1 = hi >= tp1
                hit_tp2 = hi >= tp2
            else:
                hit_sl  = hi >= sl
                hit_tp1 = lo <= tp1
                hit_tp2 = lo <= tp2

            if hit_tp2:
                outcome = "TP2"; break
            if hit_tp1:
                outcome = "TP1"; break
            if hit_sl:
                outcome = "SL";  break

        entries.append((side, entry, outcome, bars_to_exit))

    if not entries:
        return (f"🧪 Backtest ({days}d, {tf}): 0 entries | Wins 0 | TP2 0 | SL 0", "(no qualifying entries)")

    wins  = sum(1 for _,_,o,_ in entries if o in ("TP1","TP2"))
    tp2s  = sum(1 for _,_,o,_ in entries if o == "TP2")
    sls   = sum(1 for _,_,o,_ in entries if o == "SL")
    txt   = f"🧪 Backtest ({days}d, {tf}): {len(entries)} entries | Wins {wins} | TP2 {tp2s} | SL {sls}"
    detail_lines = []
    for idx,(side,entry,out,bars) in enumerate(entries[-20:], 1):
        detail_lines.append(f"{idx:02d}. {side} @ {entry:.0f} → {out} in {bars} bars")
    return txt, "\n".join(detail_lines)


# ------------- Logging & Status -------------
def record_trade(payload: dict):
    payload = dict(payload)
    payload["ts"] = datetime.now(timezone.utc).isoformat()
    _append_json_line_safe(TRADES_FILE, payload)

def get_trade_logs(n: int = 30) -> str:
    data = _load_json_safe(TRADES_FILE, [])
    if not data:
        return "No trades recorded yet."
    lines = []
    for item in data[-n:]:
        ts   = item.get("ts","")
        side = item.get("side","")
        px   = item.get("entry_price","")
        res  = item.get("result","")
        lines.append(f"{ts} | {side} @ {px} → {res}")
    return "\n".join(lines)

def get_results() -> str:
    data = _load_json_safe(TRADES_FILE, [])
    if not data:
        return "Results: 0 trades."
    wins = sum(1 for x in data if x.get("result") in ("TP1","TP2"))
    tp2  = sum(1 for x in data if x.get("result") == "TP2")
    sls  = sum(1 for x in data if x.get("result") == "SL")
    return f"Results: trades {len(data)} | wins {wins} | TP2 {tp2} | SL {sls}"

def get_bot_status() -> str:
    return (
        "📊 Current Logic:\n"
        f"- Symbol: {SYMBOL} (MEXC)\n"
        f"- TF: {SCAN_TF}\n"
        f"- Filters: Trend + RSI (Engulfing OFF)\n"
        f"- RSI band: {RSI_MIN:.0f}–{RSI_MAX:.0f}\n"
        f"- EMA: {EMA_FAST}/{EMA_SLOW}, VWAP(20)\n"
        f"- Risk: SL ${SL_CAP_BASE:.0f} (max {SL_CAP_MAX:.0f}, cushion {SL_CUSHION_DOLLARS:.0f})\n"
        f"- TP: ${TP1_DOLLARS:.0f} → ${TP2_DOLLARS:.0f}\n"
        f"- AI gate ≥ {AI_MIN:.2f}\n"
    )

def check_data_source() -> str:
    df = fetch_mexc("5m", limit=200)
    if df is None or df.empty:
        return "❌ Data source error: MEXC not responding."
    last = df.index[-1]
    return f"✅ Connected to MEXC\nLast 5m bar: {last}"

def diag_data() -> str:
    out = ["📡 MEXC diag"]
    for tf in ["1m","5m","15m","30m","1h"]:
        df = fetch_mexc(tf, limit=200)
        if df is None or df.empty:
            out.append(f"{tf}: None")
        else:
            out.append(f"{tf}: {len(df)} bars, last={df.index[-1]}")
    return "\n".join(out)

# --- AI status (for /ai or bot import) ---
def get_ai_status() -> str:
    """
    Returns a short, human-readable summary of the AI's current runtime state.
    Safe if ai_core is missing; falls back to defaults.
    """
    exploration = None
    caution     = None
    sl_streak   = None
    last_ts     = None

    # live state
    try:
        import ai_core  # optional
        st = getattr(ai_core, "_state", {}) or {}
        exploration = st.get("exploration", None)
        caution     = st.get("caution_multiplier", None)
        sl_streak   = st.get("sl_streak", None)
        last_ts     = st.get("last_outcome_ts", None)
    except Exception:
        pass

    # persisted file
    if (exploration is None) or (caution is None) or (sl_streak is None):
        try:
            state_file = os.getenv("AI_STATE_FILE", "ai_state.json")
            if os.path.exists(state_file):
                st2 = _load_json_safe(state_file, {})
                exploration = exploration if exploration is not None else st2.get("exploration", 0.05)
                caution     = caution     if caution     is not None else st2.get("caution_multiplier", 1.0)
                sl_streak   = sl_streak   if sl_streak   is not None else st2.get("sl_streak", 0)
                last_ts     = last_ts     if last_ts     is not None else st2.get("last_outcome_ts", 0)
        except Exception:
            pass

    try:
        if last_ts:
            last_dt = datetime.fromtimestamp(float(last_ts), tz=timezone.utc).astimezone()
            last_str = last_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            last_str = "—"
    except Exception:
        last_str = "—"

    try:
        exp = f"{float(exploration):.2f}" if exploration is not None else "n/a"
        cau = f"{float(caution):.2f}"     if caution     is not None else "n/a"
        sls = f"{int(sl_streak)}"         if sl_streak   is not None else "n/a"
    except Exception:
        exp, cau, sls = "n/a", "n/a", "n/a"

    return (
        "🤖 AI Status\n"
        f"- exploration: {exp}\n"
        f"- caution x:   {cau}\n"
        f"- SL streak:   {sls}\n"
        f"- last result: {last_str}\n"
        f"- gate ≥ {AI_MIN:.2f} | RSI {RSI_MIN:.0f}–{RSI_MAX:.0f} | EMA {EMA_FAST}/{EMA_SLOW}\n"
    )
