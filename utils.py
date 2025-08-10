# utils.py
import os, json, time, math
from typing import Tuple, Optional
import requests
import pandas as pd
import numpy as np

# -------------- Config (from environment) -----------------
SYMBOL              = os.getenv("SYMBOL", "BTCUSDT")
SCAN_TF             = os.getenv("SCAN_TF", "5m").lower()

# Filters
RSI_MIN             = float(os.getenv("RSI_MIN", "35"))
RSI_MAX             = float(os.getenv("RSI_MAX", "65"))
EMA_FAST            = int(os.getenv("EMA_FAST", "9"))
EMA_SLOW            = int(os.getenv("EMA_SLOW", "34"))
VWAP_WIN            = int(os.getenv("VWAP_WIN", "20"))
AI_MIN              = float(os.getenv("AI_MIN", "0.62"))

# 15m confirm + trend strength
USE_15M_CONFIRM     = os.getenv("USE_15M_CONFIRM", "true").lower() == "true"
EMA_SPREAD_MIN      = float(os.getenv("EMA_SPREAD_MIN", "0.0012"))  # strength gate

# Risk/targets
SL_CAP_BASE         = float(os.getenv("SL_CAP_BASE", "250"))
SL_CAP_MAX          = float(os.getenv("SL_CAP_MAX", "500"))
SL_CUSHION_DOLLARS  = float(os.getenv("SL_CUSHION_DOLLARS", "50"))
TP1_DOLLARS         = float(os.getenv("TP1_DOLLARS", "400"))
TP2_DOLLARS         = float(os.getenv("TP2_DOLLARS", "1200"))

# Backtest & regime shaping
COOLDOWN_BARS       = int(os.getenv("COOLDOWN_BARS", "6"))
ATR_LEN             = int(os.getenv("ATR_LEN", "14"))
ATR_MIN_USD         = float(os.getenv("ATR_MIN_USD", "60"))
MIN_VWAP_DIST       = float(os.getenv("MIN_VWAP_DIST", "30"))

# Files
TRADE_LOG_FILE      = os.getenv("TRADE_LOG_FILE", "trade_logs.json")

# Timestamps to local readout
LOCAL_TZ            = os.getenv("LOCAL_TZ", "Asia/Kolkata")

# -------------------- Data fetch (MEXC v3) ----------------
_MEXC_BASE = "https://api.mexc.com/api/v3/klines"
_TF_MAP = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h"}

def _to_local(ts_utc: pd.Timestamp) -> str:
    try:
        return ts_utc.tz_convert(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S%z")
    except Exception:
        return ts_utc.strftime("%Y-%m-%d %H:%M:%S UTC")

def fetch_mexc(tf: str = "5m", limit: int = 500) -> Optional[pd.DataFrame]:
    tf = tf.lower()
    if tf not in _TF_MAP:
        tf = "5m"
    params = {
        "symbol": SYMBOL.upper(),
        "interval": _TF_MAP[tf],
        "limit": max(100, min(int(limit), 1000))
    }
    try:
        r = requests.get(_MEXC_BASE, params=params, timeout=10)
        if r.status_code != 200:
            return None
        try:
            raw = r.json()
        except Exception:
            return None
        if not isinstance(raw, list) or len(raw) == 0:
            return None

        # MEXC returns arrays: [openTime, open, high, low, close, volume, closeTime, quoteVol, trades, takerBase, takerQuote, ignore]
        cols = ["openTime","open","high","low","close","volume","closeTime","qv","trades","tb","tq","ig"]
        df = pd.DataFrame(raw, columns=cols[:len(raw[0])])
        for c in ["open","high","low","close","volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["openTime"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        df = df.set_index("openTime").sort_index()
        df = df[["open","high","low","close","volume"]].dropna()
        return df
    except Exception:
        return None

# ------------------- Indicators ---------------------------
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    roll_up = up.ewm(alpha=1/n, adjust=False).mean()
    roll_down = down.ewm(alpha=1/n, adjust=False).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _vwap(df: pd.DataFrame, win: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = tp * df["volume"].fillna(0)
    cum_pv = pv.rolling(win).sum()
    cum_v  = df["volume"].fillna(0).rolling(win).sum()
    return (cum_pv / cum_v.replace(0,np.nan))

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    pc = df["close"].shift(1)
    tr = pd.concat([hl, (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["rsi"]      = _rsi(df["close"], 14)
    df["vwap"]     = _vwap(df, win=VWAP_WIN)
    df["atr"]      = _atr(df, ATR_LEN)
    spread = (df["ema_fast"] - df["ema_slow"]).abs() / df["close"].replace(0,np.nan)
    df["regime"]   = np.where(spread > EMA_SPREAD_MIN, "trend", "range")
    return df.dropna()

# ------------------- AI helpers ---------------------------
def _ai_score_from_df(df: pd.DataFrame, idx: int = -1) -> float:
    try:
        from ai_core import score  # optional module
        last = df.iloc[idx]
        ema_spread = float((last["ema_fast"] - last["ema_slow"]) / last["close"])
        j = max(0, idx-5)
        ema_slope  = float((df["ema_fast"].iloc[idx] - df["ema_fast"].iloc[j]) / max(1,(idx-j)) / last["close"])
        s, _ = score({"ema_spread": ema_spread, "ema_slope": ema_slope}, regime=str(last.get("regime","range")))
        return float(s)
    except Exception:
        return 0.50

def get_ai_status() -> str:
    # lightweight peek into ai_core state (optional)
    try:
        from ai_core import _state as S  # type: ignore
        return (f"🧠 AI: sl_streak {S.get('sl_streak',0)}, "
                f"caution× {S.get('caution_multiplier',1.0):.2f}, "
                f"explore {S.get('exploration',0.05):.2f}")
    except Exception:
        return "🧠 AI: default heuristics (no state)"

# ------------------- Signal helpers -----------------------
def _trend_flags(row) -> Tuple[bool,bool]:
    up = (row["ema_fast"] > row["ema_slow"]) and (row["close"] > row["vwap"])
    dn = (row["ema_fast"] < row["ema_slow"]) and (row["close"] < row["vwap"])
    return up, dn

def _rsi_ok(v: float) -> bool:
    return (RSI_MIN <= v <= RSI_MAX)

def _match_15m_at(ts: pd.Timestamp, df15: pd.DataFrame) -> Optional[pd.Series]:
    try:
        sub = df15.loc[:ts]
        if len(sub) == 0: return None
        return sub.iloc[-1]
    except Exception:
        return None

def _format_signal(side: str, entry: float, ai_score: float, src: str, ts: pd.Timestamp) -> str:
    sl  = entry - SL_CAP_BASE if side == "LONG" else entry + SL_CAP_BASE
    sl  = sl if abs(sl - entry) <= SL_CAP_MAX else (entry - SL_CAP_MAX if side=="LONG" else entry + SL_CAP_MAX)
    tp1 = entry + TP1_DOLLARS if side == "LONG" else entry - TP1_DOLLARS
    tp2 = entry + TP2_DOLLARS if side == "LONG" else entry - TP2_DOLLARS
    head = "🟢 LONG" if side=="LONG" else "🔴 SHORT"
    tstr = _to_local(ts.tz_convert(LOCAL_TZ) if hasattr(ts, "tz_convert") else ts)
    return (
        f"{head} @ {entry:.0f} | SL {sl:.0f} TP {tp1:.0f}→{tp2:.0f} [{src}]\n"
        f"AI {ai_score:.2f} | {tstr}"
    )

# ------------------- Public: scan & backtest ---------------
def scan_market(tf: str = None) -> Tuple[str, str]:
    """Returns (message_for_user, debug_detail)"""
    tf = (tf or SCAN_TF).lower()
    df5 = fetch_mexc(tf, limit=500)
    if df5 is None or len(df5) < 60:
        return ("❌ Data Error:\nNo data from MEXC right now.", "fetch_mexc returned None or too few rows")
    df5 = compute_indicators(df5)
    last5 = df5.iloc[-1]
    up5, dn5 = _trend_flags(last5)

    # 15m confirmation
    if USE_15M_CONFIRM:
        df15 = fetch_mexc("15m", limit=300)
        if df15 is None or len(df15) < 60:
            return ("ℹ️ No trade | TF 5m | 15m unavailable", "Missing 15m for confirmation")
        df15 = compute_indicators(df15)
        m15 = _match_15m_at(df5.index[-1], df15)
        if m15 is None:
            return ("ℹ️ No trade | TF 5m | 15m align fail", "No matching 15m bar")
        up15, dn15 = _trend_flags(m15)
        if (up5 and not up15) or (dn5 and not dn15):
            return (f"ℹ️ No trade | TF {tf} | Regime {last5.get('regime','range')} | 15m filter", "HTF disagrees")

    # AI + RSI gates
    ai_s = _ai_score_from_df(df5, -1)
    if ai_s < AI_MIN:
        return (f"ℹ️ No trade | TF {tf} | Regime {last5.get('regime','range')} | AI {ai_s:.2f}", "AI gate")
    if not _rsi_ok(float(last5["rsi"])):
        return (f"ℹ️ No trade | TF {tf} | Regime {last5.get('regime','range')} | AI {ai_s:.2f}", "RSI band")

    # Choose side from 5m
    if up5:
        msg = _format_signal("LONG", float(last5["close"]), ai_s, "MEXC", df5.index[-1])
        return (msg, "ok")
    if dn5:
        msg = _format_signal("SHORT", float(last5["close"]), ai_s, "MEXC", df5.index[-1])
        return (msg, "ok")

    return (f"ℹ️ No trade | TF {tf} | Regime {last5.get('regime','range')} | AI {ai_s:.2f}", "neutral trend")

def run_backtest(days: int = 2, tf: str = "5m") -> Tuple[str, str]:
    tf = tf.lower()
    bars_per_day = {"1m":1440,"5m":288,"15m":96,"30m":48,"1h":24}.get(tf,288)
    limit = min(1500, max(300, days * bars_per_day))
    df5 = fetch_mexc(tf, limit=limit)
    if df5 is None or len(df5) < 120:
        return ("❌ Backtest: unable to fetch history from MEXC.", "")
    df5 = compute_indicators(df5)

    df15 = None
    if USE_15M_CONFIRM:
        df15 = fetch_mexc("15m", limit=500)
        if df15 is None or len(df15) < 120:
            return ("❌ Backtest: 15m confirmation unavailable.", "")
        df15 = compute_indicators(df15)

    entries = []
    i = 60
    n = len(df5)
    while i < n-2:
        row  = df5.iloc[i]
        up5, dn5 = _trend_flags(row)
        rsi_ok   = _rsi_ok(float(row["rsi"]))
        if not rsi_ok:
            i += 1; continue

        if USE_15M_CONFIRM:
            m15 = _match_15m_at(df5.index[i], df15)
            if m15 is None:
                i += 1; continue
            up15, dn15 = _trend_flags(m15)
            if (up5 and not up15) or (dn5 and not dn15):
                i += 1; continue

        ai_s = _ai_score_from_df(df5, i)
        if ai_s < AI_MIN:
            i += 1; continue

        side = "LONG" if up5 else ("SHORT" if dn5 else None)
        if side is None:
            i += 1; continue

        entry = float(row["close"])
        sl    = entry - SL_CAP_BASE if side=="LONG" else entry + SL_CAP_BASE
        sl    = sl if abs(sl-entry) <= SL_CAP_MAX else (entry - SL_CAP_MAX if side=="LONG" else entry + SL_CAP_MAX)
        tp1   = entry + TP1_DOLLARS if side=="LONG" else entry - TP1_DOLLARS
        tp2   = entry + TP2_DOLLARS if side=="LONG" else entry - TP2_DOLLARS

        outcome, bars_to_exit = "OPEN", 0
        j_limit = min(i+220, n-1)
        for j in range(i+1, j_limit):
            hi = float(df5["high"].iloc[j]); lo = float(df5["low"].iloc[j])
            bars_to_exit = j - i
            if side == "LONG":
                if hi >= tp2: outcome="TP2"; break
                if hi >= tp1: outcome="TP1"; break
                if lo <= sl:  outcome="SL";  break
            else:
                if lo <= tp2: outcome="TP2"; break
                if lo <= tp1: outcome="TP1"; break
                if hi >= sl:  outcome="SL";  break

        entries.append((side, entry, outcome, bars_to_exit, ai_s))
        i = (j if outcome != "OPEN" else j_limit) + COOLDOWN_BARS

    if not entries:
        return (f"🧪 Backtest ({days}d, {tf}{' + 15m' if USE_15M_CONFIRM else ''}): 0 entries | Wins 0 | TP2 0 | SL 0",
                "(no qualifying entries)")

    wins = sum(1 for *_, o, __, ___ in entries if o in ("TP1","TP2"))
    tp2s = sum(1 for *_, o, __, ___ in entries if o == "TP2")
    sls  = sum(1 for *_, o, __, ___ in entries if o == "SL")
    hdr  = f"🧪 Backtest ({days}d, {tf}{' + 15m' if USE_15M_CONFIRM else ''}): {len(entries)} entries | Wins {wins} | TP2 {tp2s} | SL {sls}"
    detail = []
    for k,(side,entry,out,bars,ais) in enumerate(entries[-20:],1):
        detail.append(f"{k:02d}. {side} @ {entry:.0f} → {out} in {bars} bars | AI {ais:.2f}")
    return hdr, "\n".join(detail)

# -------------------- Diagnostics / Status ----------------
def diag_data() -> str:
    parts = []
    for tf in ["1m","5m","15m","30m","1h"]:
        df = fetch_mexc(tf, limit=200)
        if df is None or len(df) == 0:
            parts.append(f"{tf}: None")
        else:
            last = df.index[-1]
            parts.append(f"{tf}: {len(df)} bars, last={_to_local(last)}")
    return "📡 MEXC diag\n" + "\n".join(parts)

def get_bot_status() -> str:
    return (
        "📊 Current Logic:\n"
        f"- Symbol: {SYMBOL} (MEXC)\n"
        f"- TF: {SCAN_TF} (15m confirm: {'ON' if USE_15M_CONFIRM else 'OFF'})\n"
        f"- Filters: Trend + RSI (no engulfing)\n"
        f"- RSI band: {RSI_MIN:.0f}–{RSI_MAX:.0f}\n"
        f"- EMA: {EMA_FAST}/{EMA_SLOW}, VWAP({VWAP_WIN}), spread>{EMA_SPREAD_MIN}\n"
        f"- Risk: SL ${SL_CAP_BASE:.0f} (max {SL_CAP_MAX:.0f}, cushion {SL_CUSHION_DOLLARS:.0f})\n"
        f"- TP: ${TP1_DOLLARS:.0f} → ${TP2_DOLLARS:.0f}\n"
        f"- AI gate ≥ {AI_MIN:.2f}\n"
    )

# -------------------- Results & Logs ----------------------
def _read_json_file(path: str):
    try:
        if not os.path.exists(path): return []
        with open(path, "r") as f:
            txt = f.read().strip()
            if not txt:
                return []
            return json.loads(txt)
    except Exception:
        return []

def get_trade_logs(n: int = 30) -> str:
    logs = _read_json_file(TRADE_LOG_FILE)
    if not logs:
        return "🗂️ No trades logged yet."
    out = []
    for row in logs[-n:]:
        t = row.get("ts","")
        side = row.get("side","?")
        ent = row.get("entry","?")
        res = row.get("result","OPEN")
        out.append(f"{t} | {side} @ {ent} → {res}")
    return "🗂️ Last trades:\n" + "\n".join(out)

def get_results() -> str:
    logs = _read_json_file(TRADE_LOG_FILE)
    if not logs:
        return "[0, 0, 0, 0]"
    wins = sum(1 for r in logs if r.get("result") in ("TP1","TP2"))
    tp2  = sum(1 for r in logs if r.get("result") == "TP2")
    sls  = sum(1 for r in logs if r.get("result") == "SL")
    total= len(logs)
    return json.dumps([total, wins, tp2, sls])

def record_trade(side: str, entry: float, result: str):
    row = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "symbol": SYMBOL,
        "side": side,
        "entry": float(entry),
        "result": result
    }
    try:
        data = _read_json_file(TRADE_LOG_FILE)
        data.append(row)
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass
