# utils.py
import os, json, time, math
from datetime import datetime
from typing import Optional, Tuple
import requests
import pandas as pd
import numpy as np

# =========================
# HARD-CODED HISTORY LIMITS
# =========================
ONE_MIN_LIMIT      = 500   # for diag & momentum checks
FIVE_MIN_LIMIT     = 700   # ~2 days of 5m bars
FIFTEEN_MIN_LIMIT  = 300   # ~2 days of 15m bars
THIRTY_MIN_LIMIT   = 300   # optional diag
ONE_HOUR_LIMIT     = 300   # optional diag

_LIMITS = {
    "1m":  ONE_MIN_LIMIT,
    "5m":  FIVE_MIN_LIMIT,
    "15m": FIFTEEN_MIN_LIMIT,
    "30m": THIRTY_MIN_LIMIT,
    "1h":  ONE_HOUR_LIMIT,
}

# =========================
# RISK / TP DEFAULTS (USD)
# =========================
SL_CAP_BASE         = float(os.getenv("SL_CAP_BASE", "300"))    # default SL budget
SL_CAP_MAX          = float(os.getenv("SL_CAP_MAX",  "500"))    # maximum SL if AI expands
SL_CUSHION_DOLLARS  = float(os.getenv("SL_CUSHION_DOLLARS", "50"))
TP1_DOLLARS         = float(os.getenv("TP1_DOLLARS", "400"))
TP2_DOLLARS         = float(os.getenv("TP2_DOLLARS", "1200"))

# AI gate for entries
AI_MIN_SCORE        = float(os.getenv("AI_MIN_SCORE", "0.52"))

# RSI gate enabled?
USE_RSI             = os.getenv("USE_RSI", "true").lower() == "true"
RSI_MIN             = int(os.getenv("RSI_MIN", "25"))
RSI_MAX             = int(os.getenv("RSI_MAX", "75"))

# Data / logs / tz
SYMBOL              = os.getenv("SYMBOL", "BTCUSDT")
TRADE_LOG_FILE      = os.getenv("TRADE_LOG_FILE", "trade_logs.json")
OPEN_TRADE_FILE     = os.getenv("OPEN_TRADE_FILE", "open_trade.json")   # new file to store current open idea
TZ                  = os.getenv("TZ_NAME", "Asia/Kolkata")

# Momentum ping cadence (bot side can call momentum_pulse() every ~60s)
PING_COOLDOWN_SEC_1M = 50
PING_COOLDOWN_SEC_5M = 50

# =========================
# Try to wire ai_core (dopamine & adaptation)
# =========================
def _noop_reward(**kwargs): return 0.0
def _noop_register(_): pass
def _fallback_ai_score(features: dict, regime: str):
    # simple, stable scorer
    spread = features.get("ema_spread", 0.0)   # (ema5-ema20)/close
    slope  = features.get("ema_slope", 0.0)    # ema20 slope normalized
    base   = 0.55 + 0.10 * np.clip(spread, -0.1, 0.1) + 0.05 * np.clip(slope, -0.1, 0.1)
    return max(0.0, min(1.0, float(base))), 0.05

try:
    from ai_core import score as ai_score_model, compute_reward, register_outcome
except Exception:
    ai_score_model = _fallback_ai_score
    compute_reward = _noop_reward
    register_outcome = _noop_register

# =========================
# MEXC v3 spot klines fetch
# =========================
MEXC_V3_URL = "https://api.mexc.com/api/v3/klines"
_MEXC_TF_MAP = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h"}

def mexc_fetch(tf: str, limit: int = 200) -> Optional[pd.DataFrame]:
    """
    Robust MEXC v3 klines fetcher (spot). Returns DataFrame with:
    index = open_time (Asia/Kolkata), columns = open, high, low, close, volume
    Handles 8–12 column array responses.
    """
    try:
        iv = _MEXC_TF_MAP.get(tf, tf)
        params = {"symbol": SYMBOL, "interval": iv, "limit": int(limit)}
        r = requests.get(MEXC_V3_URL, params=params, timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None

        cols_full = [
            "open_time","open","high","low","close","volume",
            "close_time","quote_volume","trade_count",
            "taker_buy_base","taker_buy_quote","ignore"
        ]
        n = len(data[0])
        df = pd.DataFrame(data, columns=cols_full[:n])

        for c in ("open","high","low","close","volume"):
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        if "open_time" in df.columns:
            idx = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(TZ)
            df.index = idx

        df = df[["open","high","low","close","volume"]].dropna()
        return df
    except Exception:
        return None

# =========================
# INDICATORS & HELPERS
# =========================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ema5"]  = d["close"].ewm(span=5,  adjust=False).mean()
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    vv = d["volume"].replace(0, np.nan)
    d["vwap"] = (d["close"] * d["volume"]).cumsum() / vv.cumsum()
    # RSI(14)
    delta = d["close"].diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    d["rsi"] = 100 - 100/(1 + rs)
    return d

def htf_trend(df15: pd.DataFrame) -> str:
    d = compute_indicators(df15)
    if len(d) < 20:
        return "range"
    return "up" if d["close"].iloc[-1] > d["ema20"].iloc[-1] else "down"

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

# =========================
# OPEN TRADE STATE (persist to file)
# =========================
def _load_open() -> Optional[dict]:
    try:
        if not os.path.exists(OPEN_TRADE_FILE):
            return None
        x = json.load(open(OPEN_TRADE_FILE, "r"))
        return x if isinstance(x, dict) else None
    except Exception:
        return None

def _save_open(d: Optional[dict]):
    try:
        if d is None:
            if os.path.exists(OPEN_TRADE_FILE):
                os.remove(OPEN_TRADE_FILE)
            return
        json.dump(d, open(OPEN_TRADE_FILE, "w"))
    except Exception:
        pass

def _load_logs() -> list:
    try:
        if not os.path.exists(TRADE_LOG_FILE):
            return []
        data = json.load(open(TRADE_LOG_FILE, "r"))
        return data if isinstance(data, list) else []
    except Exception:
        return []

def _save_logs(rows: list):
    try:
        json.dump(rows, open(TRADE_LOG_FILE, "w"))
    except Exception:
        pass

def record_trade(entry: dict) -> None:
    rows = _load_logs()
    rows.append(entry)
    _save_logs(rows)

# =========================
# ENTRY FORMATTER
# =========================
def _fmt_signal(side: str, px: float, sl: float, tp1: float, tp2: float, src="MEXC") -> str:
    arrow = "🟢 LONG" if side == "long" else "🔴 SHORT"
    return f"{arrow} @ {px:.0f} | SL {sl:.0f} TP {tp1:.0f}→{tp2:.0f} [{src}]"

# =========================
# LIVE SCAN (used by /scan and /forcescan)
# =========================
def scan_market() -> Tuple[str, bool]:
    # Block if there’s already an open trade
    open_pos = _load_open()
    if open_pos is not None:
        side = open_pos.get("side","").upper()
        e = open_pos.get("entry", 0)
        return (f"ℹ️ Existing trade open: {side} @ {e}. No new entry.", False)

    df5  = mexc_fetch("5m",  limit=FIVE_MIN_LIMIT)
    df15 = mexc_fetch("15m", limit=FIFTEEN_MIN_LIMIT)
    if df5 is None or df5.empty or df15 is None or df15.empty:
        return ("❌ Data Error:\nNo data from MEXC.", False)

    d5  = compute_indicators(df5)
    d15 = compute_indicators(df15)
    regime = htf_trend(d15)
    if regime == "range":
        return ("ℹ️ No trade | TF 5m | Regime range", False)

    last5 = d5.iloc[-1]
    close = float(last5["close"])

    # regime gate
    if regime == "up":
        cond = (last5["close"] > last5["vwap"]) and (last5["ema5"] > last5["ema20"])
        side = "long"
    else:
        cond = (last5["close"] < last5["vwap"]) and (last5["ema5"] < last5["ema20"])
        side = "short"

    # rsi gate
    if USE_RSI:
        rsi_ok = RSI_MIN <= float(last5["rsi"]) <= RSI_MAX
        if not rsi_ok:
            return (f"ℹ️ No trade | TF 5m | Regime {regime} | RSI gate", False)

    # AI score (use ai_core.score if available)
    ema_spread = (float(last5["ema5"]) - float(last5["ema20"])) / max(1.0, close)
    ema20_slope = (d5["ema20"].iloc[-1] - d5["ema20"].iloc[-5]) / max(1.0, 4.0*close)
    p, _explore = ai_score_model({"ema_spread": ema_spread, "ema_slope": ema20_slope}, regime)
    if (not cond) or (p < AI_MIN_SCORE):
        return (f"ℹ️ No trade | TF 5m | Regime {regime} | AI {p:.2f}", False)

    # Create trade levels
    if side == "long":
        sl  = close - SL_CAP_BASE
        tp1 = close + TP1_DOLLARS
        tp2 = close + TP2_DOLLARS
    else:
        sl  = close + SL_CAP_BASE
        tp1 = close - TP1_DOLLARS
        tp2 = close - TP2_DOLLARS

    # Persist open trade
    open_pos = {
        "symbol": SYMBOL,
        "source": "MEXC",
        "side": side,
        "entry": float(close),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "breakeven": False,          # becomes True after TP1 is tagged
        "opened_at": _now_iso(),
        "last_ping_1m": 0,
        "last_ping_5m": 0
    }
    _save_open(open_pos)

    # Log creation in trade logs (OPEN)
    record_trade({
        "time": _now_iso(),
        "side": side,
        "price": float(close),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "outcome": "OPEN",
        "source": "entry"
    })

    msg = _fmt_signal(side, close, sl, tp1, tp2, "MEXC") + f"\n🤖 AI={p:.2f} | Regime={regime}"
    return (msg, True)

# =========================
# MOMENTUM EVALUATION & MANAGEMENT
# =========================
def _current_price_1m() -> Optional[float]:
    d1 = mexc_fetch("1m", limit=2)
    if d1 is None or d1.empty: return None
    return float(d1["close"].iloc[-1])

def _momentum_view(tf: str) -> Optional[str]:
    df = mexc_fetch(tf, limit=ONE_MIN_LIMIT if tf=="1m" else (FIVE_MIN_LIMIT if tf=="5m" else 200))
    if df is None or df.empty: return None
    d = compute_indicators(df)
    last = d.iloc[-1]
    up   = (last["close"] > last["vwap"]) and (last["ema5"] > last["ema20"]) and (float(last["rsi"]) >= 50.0)
    down = (last["close"] < last["vwap"]) and (last["ema5"] < last["ema20"]) and (float(last["rsi"]) <= 50.0)
    if up: return "up"
    if down: return "down"
    return "mixed"

def _close_trade(outcome: str, px: float):
    # write outcome to logs & clear open file; reward the AI
    rows = _load_logs()
    # find last OPEN to close
    idx = None
    for i in range(len(rows)-1, -1, -1):
        if rows[i].get("outcome") == "OPEN":
            idx = i
            break
    if idx is not None:
        rows[idx]["outcome"] = outcome
        rows[idx]["exit_price"] = float(px)
        rows[idx]["exit_time"]  = _now_iso()
        _save_logs(rows)

    # Register outcome to AI (best-effort; we don’t have all metrics here → simple reward)
    try:
        pnl = 0.0
        if idx is not None:
            ent = float(rows[idx].get("price", px))
            pnl = (px - ent) if rows[idx].get("side")=="long" else (ent - px)
        reward = compute_reward(
            outcome=outcome, pnl=pnl, bars_to_exit=0,
            tp2_hit=(outcome=="TP2"), tp1_hit=(outcome in ("TP1","TP2")),
            sl_expanded=False, sl_dollars=SL_CAP_BASE, sl_cap_base=SL_CAP_BASE,
            trailing_respected=True, momentum_aligned_bars=0, duplicate_entry=False
        )
        register_outcome(outcome)
    except Exception:
        pass

    _save_open(None)

def momentum_pulse() -> Optional[str]:
    """
    Call this every ~60s from your bot background thread.
    - Moves SL→BE after TP1
    - Suggests early book on weakness
    - Encourages hold on strength
    - Closes trade when SL/TP is tagged, logs outcome and notifies
    Returns a short message (or None if no ping).
    """
    pos = _load_open()
    if pos is None:
        return None

    now = time.time()
    side = pos["side"]
    entry = float(pos["entry"])
    sl   = float(pos["sl"])
    tp1  = float(pos["tp1"])
    tp2  = float(pos["tp2"])
    breakeven = bool(pos.get("breakeven", False))

    # latest 1m price and candle HL for tag checks
    d1 = mexc_fetch("1m", limit=2)
    if d1 is None or d1.empty:
        return None
    last = d1.iloc[-1]
    price = float(last["close"])
    high  = float(last["high"])
    low   = float(last["low"])

    # Check TP/SL tags first (realized outcomes)
    if side == "long":
        if high >= tp2:
            _close_trade("TP2", tp2)
            return f"🏁 TP2 HIT @ {tp2:.0f} — trade closed."
        if high >= tp1 and not breakeven:
            pos["breakeven"] = True
            pos["sl"] = entry  # move to BE
            _save_open(pos)
            return f"🔒 Moved SL → BE @ {entry:.0f} (TP1 tagged)."
        if low <= sl:
            _close_trade("SL", sl)
            return f"🛑 SL HIT @ {sl:.0f} — trade closed."
    else:  # short
        if low <= tp2:
            _close_trade("TP2", tp2)
            return f"🏁 TP2 HIT @ {tp2:.0f} — trade closed."
        if low <= tp1 and not breakeven:
            pos["breakeven"] = True
            pos["sl"] = entry
            _save_open(pos)
            return f"🔒 Moved SL → BE @ {entry:.0f} (TP1 tagged)."
        if high >= sl:
            _close_trade("SL", sl)
            return f"🛑 SL HIT @ {sl:.0f} — trade closed."

    # Momentum view (1m & 5m)
    v1 = _momentum_view("1m")
    v5 = _momentum_view("5m")

    # Respect ping cooldowns
    out_msgs = []
    last1 = float(pos.get("last_ping_1m", 0))
    last5 = float(pos.get("last_ping_5m", 0))

    # Construct strength/weakness relative to side
    def _favor(view: Optional[str]) -> Optional[str]:
        if view is None: return None
        if side == "long":
            if view == "up": return "favor"
            if view == "down": return "against"
            return "mixed"
        else:
            if view == "down": return "favor"
            if view == "up":   return "against"
            return "mixed"

    f1 = _favor(v1)
    f5 = _favor(v5)

    # Weakness → suggest early book (only after some profit over BE)
    up_pnl = (price - entry) if side == "long" else (entry - price)
    small_gain = up_pnl >= 100.0  # at least +$100 before nagging
    if (f1 == "against" or f5 == "against") and small_gain:
        if now - last1 > PING_COOLDOWN_SEC_1M:
            out_msgs.append("⚠️ Momentum weakening — consider **booking partial**.")
            pos["last_ping_1m"] = now

    # Strength → hold guidance toward TP2
    if (f1 == "favor" or f5 == "favor") and up_pnl >= 50.0:
        if now - last5 > PING_COOLDOWN_SEC_5M:
            out_msgs.append("🏎️ Momentum strong — **hold toward TP2**.")
            pos["last_ping_5m"] = now

    if out_msgs:
        _save_open(pos)
        return "\n".join(out_msgs)

    return None

# =========================
# BACKTEST (2 days default)
# =========================
def run_backtest(days: int = 2) -> str:
    try:
        df5  = mexc_fetch("5m",  limit=FIVE_MIN_LIMIT)
        df15 = mexc_fetch("15m", limit=FIFTEEN_MIN_LIMIT)
        if df5 is None or df5.empty or df15 is None or df15.empty:
            return "🧪 Backtest (2d, 5m): 0 entries | Wins 0 | TP2 0 | SL 0\n(no qualifying entries)"

        end = df5.index[-1]
        start = end - pd.Timedelta(days=days)
        d5  = compute_indicators(df5.loc[df5.index >= start])
        d15 = compute_indicators(df15.loc[df15.index >= (end - pd.Timedelta(days=days*2))])
        if len(d5) < 40:
            return "🧪 Backtest (2d, 5m): 0 entries | Wins 0 | TP2 0 | SL 0\n(no qualifying entries)"

        regime = htf_trend(d15)
        if regime == "range":
            return "🧪 Backtest (2d, 5m): 0 entries | Wins 0 | TP2 0 | SL 0\n(no qualifying entries)"

        entries=wins=tp2hits=sls=0
        lines=[]
        for i in range(25, len(d5)-1):
            row = d5.iloc[i]
            close = float(row["close"])
            if USE_RSI and not (RSI_MIN <= float(row["rsi"]) <= RSI_MAX):
                continue

            if regime == "up":
                cond = (row["close"] > row["vwap"]) and (row["ema5"] > row["ema20"])
                side = "long"
            else:
                cond = (row["close"] < row["vwap"]) and (row["ema5"] < row["ema20"])
                side = "short"

            ema_spread = (float(row["ema5"]) - float(row["ema20"])) / max(1.0, close)
            ema20_slope = (d5["ema20"].iloc[i] - d5["ema20"].iloc[i-4]) / max(1.0, 4.0*close)
            p,_ = ai_score_model({"ema_spread": ema_spread, "ema_slope": ema20_slope}, regime)
            if (not cond) or p < AI_MIN_SCORE:
                continue

            entries += 1
            if side=="long":
                sl  = close - SL_CAP_BASE
                tp1 = close + TP1_DOLLARS
                tp2 = close + TP2_DOLLARS
                fwd = d5.iloc[i+1:i+60].copy()
                hit_tp2 = (fwd["high"] >= tp2).any()
                hit_tp1 = (fwd["high"] >= tp1).any()
                # breakeven after TP1
                hit_sl  = (fwd["low"] <= (close if hit_tp1 else sl)).any()
            else:
                sl  = close + SL_CAP_BASE
                tp1 = close - TP1_DOLLARS
                tp2 = close - TP2_DOLLARS
                fwd = d5.iloc[i+1:i+60].copy()
                hit_tp2 = (fwd["low"] <= tp2).any()
                hit_tp1 = (fwd["low"] <= tp1).any()
                hit_sl  = (fwd["high"] >= (close if hit_tp1 else sl)).any()

            outcome="OPEN"
            if hit_sl:
                outcome="SL"; sls+=1
            elif hit_tp2:
                outcome="TP2"; tp2hits+=1; wins+=1
            elif hit_tp1:
                outcome="TP1"; wins+=1

            if len(lines)<40:
                lines.append(f"{entries:02d}. {side.upper()} @ {close:.0f} → {outcome}")

        if entries==0:
            return "🧪 Backtest (2d, 5m): 0 entries | Wins 0 | TP2 0 | SL 0\n(no qualifying entries)"
        head = f"🧪 Backtest (2d, 5m): {entries} entries | Wins {wins} | TP2 {tp2hits} | SL {sls}"
        return head + ("\n" + "\n".join(lines) if lines else "")
    except Exception as e:
        return f"❌ Backtest error: {e}"

# =========================
# DIAG / STATUS / RESULTS / LOGS
# =========================
def diag_data() -> str:
    lines=[]
    for tf, lim in [("1m", ONE_MIN_LIMIT), ("5m", FIVE_MIN_LIMIT),
                    ("15m", FIFTEEN_MIN_LIMIT), ("30m", THIRTY_MIN_LIMIT),
                    ("1h", ONE_HOUR_LIMIT)]:
        try:
            df = mexc_fetch(tf, limit=lim)
            if df is not None and not df.empty:
                lines.append(f"{tf}: {len(df)} bars, last={df.index[-1]}")
            else:
                lines.append(f"{tf}: None")
        except Exception as e:
            lines.append(f"{tf}: error {e}")
    return "📡 MEXC diag\n" + "\n".join(lines)

def get_bot_status() -> str:
    open_pos = _load_open()
    open_line = "none" if open_pos is None else f'{open_pos.get("side","").upper()} @ {open_pos.get("entry")}'
    return (
        "📊 Current Logic:\n"
        f"- Exchange: MEXC, Symbol: {SYMBOL}\n"
        "- Entry TF: 5m, HTF filter: 15m\n"
        f"- VWAP/EMA + {'RSI ' if USE_RSI else ''}AI≥{AI_MIN_SCORE:.2f}\n"
        f"- $SL cap {SL_CAP_BASE:.1f}→{SL_CAP_MAX:.1f} (cushion {SL_CUSHION_DOLLARS:.1f})\n"
        f"- $TPs {TP1_DOLLARS:.1f}/{TP2_DOLLARS:.1f}\n"
        "- Momentum ping: every 60s (1m & 5m)\n"
        f"- Open: {open_line}"
    )

def get_trade_logs(n: int = 30) -> str:
    rows = _load_logs()
    if not rows:
        return "No trades yet."
    lines=[]
    for r in rows[-n:]:
        t = r.get("time","")
        s = r.get("side","")
        p = r.get("price","")
        o = r.get("outcome","OPEN")
        lines.append(f"{t} {s.upper()} @ {p} → {o}")
    return "Last trades:\n" + "\n".join(lines)

def get_results() -> str:
    rows = _load_logs()
    if not rows:
        return "[0, 0, 0, 0]"
    wins = sum(1 for r in rows if r.get("outcome") in ("TP1","TP2"))
    tp2  = sum(1 for r in rows if r.get("outcome") == "TP2")
    sls  = sum(1 for r in rows if r.get("outcome") == "SL")
    total = len(rows)
    return json.dumps([total, wins, tp2, sls])
