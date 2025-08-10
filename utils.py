import os, json, time, math, threading
from datetime import datetime, timedelta, timezone
import requests
import pandas as pd
import numpy as np

# ---------- ENV / CONFIG ----------
SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()
PRIMARY_TF = os.getenv("PRIMARY_TF", "5m").lower()          # "5m" default
MOMENTUM_TF = os.getenv("MOMENTUM_TF", "1m").lower()        # ping on 1m
FILTER_TF = os.getenv("FILTER_TF", "15m").lower()           # HTF filter
FIVE_MIN_LIMIT     = int(os.getenv("FIVE_MIN_LIMIT", "700"))   # ~2 days of 5m bars
FIFTEEN_MIN_LIMIT  = int(os.getenv("FIFTEEN_MIN_LIMIT", "300"))# ~2 days of 15m bars
AI_THRESHOLD = float(os.getenv("AI_THRESHOLD", "0.52"))     # gate to allow entries

SL_CAP_BASE = float(os.getenv("SL_CAP_BASE", "300"))
SL_CAP_MAX  = float(os.getenv("SL_CAP_MAX", "500"))
SL_CUSHION  = float(os.getenv("SL_CUSHION_DOLLARS", "50"))  # extra room if AI wants

TP1_DOLLARS = float(os.getenv("TP1_DOLLARS", "600"))
TP2_DOLLARS = float(os.getenv("TP2_DOLLARS", "1500"))

PING_INTERVAL_SEC = int(os.getenv("PING_INTERVAL_SEC", "60"))
TZ = timezone(timedelta(hours=5, minutes=30))  # Asia/Kolkata

OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")     # for background pings

# Files
LOG_FILE_CANDIDATES = ["trade_logs.json", "trades.json"]
def _resolve_log_path():
    for p in LOG_FILE_CANDIDATES:
        if os.path.exists(p):
            return p
    return LOG_FILE_CANDIDATES[0]
LOG_FILE = _resolve_log_path()
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        f.write("[]")

# AI
try:
    from ai_core import compute_reward, online_update, register_outcome
    _AI_OK = True
except Exception:
    _AI_OK = False

# In-memory active trade
_ACTIVE = None           # dict with keys: side, entry, sl, tp1, tp2, ts, expanded, tp1_hit
_LAST_PING = 0.0
_LOCK = threading.Lock()

# ---------- HELPERS ----------
def _mexc_klines(symbol: str, interval: str, limit: int = 200):
    """
    MEXC v3 klines (spot). Some regions return 12 columns (Binance-style),
    others return 8 columns. Parse both and normalize to the columns we need.
    """
    url = "https://api.mexc.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = requests.get(url, params=params, timeout=12)
    if r.status_code != 200:
        raise RuntimeError(f"MEXC {interval} {r.status_code} | {url}")

    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError(f"MEXC {interval} returned no list")

    # Build a DataFrame from raw rows (variable-length)
    df_raw = pd.DataFrame(data)

    # 12-col layout: 0..11
    #  0 open_time(ms),1 open,2 high,3 low,4 close,5 volume,
    #  6 close_time(ms),7 quote_vol,8 trades,9 buy_base,10 buy_quote,11 ignore
    # 8-col layout (observed in your region): 0..7
    #  0 open_time(ms),1 open,2 high,3 low,4 close,5 volume,
    #  6 close_time(ms),7 quote_vol

    # Map common fields safely (present in both)
    colmap = {
        0: "open_time", 1: "open", 2: "high", 3: "low",
        4: "close", 5: "volume", 6: "close_time", 7: "quote_asset_vol"
    }
    # Extra (only if 12 columns exist)
    extra_map = {8: "trades", 9: "buy_base", 10: "buy_quote", 11: "ignore"}

    # Rename what exists
    rename_dict = {}
    for i, name in colmap.items():
        if i in df_raw.columns:
            rename_dict[i] = name
    for i, name in extra_map.items():
        if i in df_raw.columns:
            rename_dict[i] = name

    df = df_raw.rename(columns=rename_dict)

    # Keep only the fields we actually use downstream
    needed = ["open_time", "open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise RuntimeError(f"MEXC {interval} unsupported layout (missing {missing}); got {len(df_raw.columns)} columns")

    # Type conversions
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms").dt.tz_localize("UTC").dt.tz_convert(TZ)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[["open_time", "open", "high", "low", "close", "volume"]].dropna()
    df = df.set_index("open_time")
    return df

def _vwap(df: pd.DataFrame):
    pv = (df["close"] * df["volume"]).cumsum()
    vv = df["volume"].cumsum().replace(0, np.nan)
    return pv / vv

def _ema(s, n): return s.ewm(span=n, adjust=False).mean()

def _regime(df5: pd.DataFrame):
    """rough trend/range read from 5m."""
    ema9 = _ema(df5["close"], 9)
    ema21 = _ema(df5["close"], 21)
    spread = (ema9 - ema21).iloc[-1]
    atr = (df5["high"] - df5["low"]).rolling(14).mean().iloc[-1]
    choppy = (abs(spread) < atr*0.15)
    return ("range" if choppy else "trend"), float(spread)

def _ai_score(features: dict, regime: str):
    """Light proxy when ai_core not available."""
    if _AI_OK:
        # ai_core.score returns (p, exploration) in previous iterations,
        # but we only have reward/update/register here.
        # So derive a simple p from features:
        pass
    # Simple fallback: normalized ema_spread + slope
    p = 0.5 + 0.2*features.get("ema_spread", 0.0) + 0.05*features.get("ema_slope", 0.0)
    return max(0.0, min(1.0, p))

def _load_logs():
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _save_logs(rows):
    with open(LOG_FILE, "w") as f:
        json.dump(rows, f, ensure_ascii=False)

def _now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

# ---------- CORE MARKET OPS ----------
def fetch_all():
    """Fetch 1m/5m/15m for BTCUSDT from MEXC."""
    d1 = _mexc_klines(SYMBOL, "1m", 200)
    d5 = _mexc_klines(SYMBOL, "5m", 200)
    d15 = _mexc_klines(SYMBOL, "15m", 200)
    return d1, d5, d15

def compute_indicators(df: pd.DataFrame):
    out = df.copy()
    out["ema9"]  = _ema(out["close"], 9)
    out["ema21"] = _ema(out["close"], 21)
    out["vwap"]  = _vwap(out)
    out["rsi"]   = ta_rsi(out["close"], 14)
    return out

def ta_rsi(series, length=14):
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -1*delta.clip(upper=0.0)
    ma_up = up.ewm(com=length-1, adjust=False).mean()
    ma_down = down.ewm(com=length-1, adjust=False).mean()
    rs = ma_up / ma_down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

# ---------- SIGNAL / ENTRY ----------
def _build_signal(d5: pd.DataFrame, d15: pd.DataFrame):
    """Return (side, entry, sl, tp1, tp2, score, details) or (None, ...)"""
    # indicators
    d5i = compute_indicators(d5)
    d15i = compute_indicators(d15)

    c5  = float(d5i["close"].iloc[-1])
    e9  = float(d5i["ema9"].iloc[-1])
    e21 = float(d5i["ema21"].iloc[-1])
    vw5 = float(d5i["vwap"].iloc[-1])
    rsi = float(d5i["rsi"].iloc[-1])

    e9slope = float((d5i["ema9"].iloc[-1] - d5i["ema9"].iloc[-4]) / max(1e-6, d5i["ema9"].iloc[-4]))
    spread = (e9 - e21) / max(1e-6, c5)

    # HTF filter (15m)
    c15  = float(d15i["close"].iloc[-1])
    vw15 = float(d15i["vwap"].iloc[-1])
    htf_ok_long  = (c15 > vw15)
    htf_ok_short = (c15 < vw15)

    features = {"ema_spread": spread, "ema_slope": e9slope}
    regime, reg_spread = _regime(d5)
    score = _ai_score(features, regime)

    # Base side from 5m:
    want_long  = (c5 > vw5 and e9 > e21 and rsi > 45)
    want_short = (c5 < vw5 and e9 < e21 and rsi < 55)

    side = None
    if want_long and htf_ok_long and score >= AI_THRESHOLD:
        side = "LONG"
    elif want_short and htf_ok_short and score >= AI_THRESHOLD:
        side = "SHORT"

    if not side:
        return None, None, None, None, None, score, f"TF 5m | Regime {regime}"

    # Price-based $ SL/TP
    if side == "LONG":
        entry = c5
        sl    = entry - min(SL_CAP_MAX, SL_CAP_BASE + SL_CUSHION)
        tp1   = entry + TP1_DOLLARS
        tp2   = entry + TP2_DOLLARS
    else:
        entry = c5
        sl    = entry + min(SL_CAP_MAX, SL_CAP_BASE + SL_CUSHION)
        tp1   = entry - TP1_DOLLARS
        tp2   = entry - TP2_DOLLARS

    details = f"TF 5m | Regime {regime}"
    return side, entry, sl, tp1, tp2, score, details

def record_trade(trade: dict):
    rows = _load_logs()
    rows.append(trade)
    _save_logs(rows)

def scan_market():
    """Used by /scan and /forcescan. Also used by auto background."""
    try:
        d1, d5, d15 = fetch_all()
    except Exception as e:
        return f"❌ Data Error:\n{str(e)}", "ERR"

    side, entry, sl, tp1, tp2, score, details = _build_signal(d5, d15)
    if not side:
        return f"ℹ️ No trade | {details} | AI {score:.2f}", "NONE"

    with _LOCK:
        global _ACTIVE
        if _ACTIVE is not None:
            return "ℹ️ Already in a trade; skipping new signal.", "HOLD"

        _ACTIVE = {
            "ts": _now_str(),
            "symbol": SYMBOL,
            "side": side,
            "entry": float(entry),
            "sl": float(sl),
            "tp1": float(tp1),
            "tp2": float(tp2),
            "expanded": False,
            "tp1_hit": False
        }
        record_trade({"event": "OPEN", **_ACTIVE})

    msg = (f"{'🟢' if side=='LONG' else '🔴'} {side} @ {entry:.2f} | "
           f"SL {sl:.2f} TP {tp1:.2f}→{tp2:.2f} [MEXC]\n"
           f"Score {score:.2f} | {details}")
    return msg, "OPEN"

# ---------- MANAGER / PINGS ----------
def _check_close(px: float):
    """Return outcome or None; apply AI reward/update if closing."""
    with _LOCK:
        global _ACTIVE
        a = _ACTIVE
        if a is None:
            return None

        side = a["side"]
        entry, sl, tp1, tp2 = a["entry"], a["sl"], a["tp1"], a["tp2"]

        # TP1
        if side == "LONG" and px >= tp1 and not a.get("tp1_hit"):
            a["tp1_hit"] = True
            record_trade({"event":"TP1", "ts":_now_str(), "px":px})
            return "TP1"

        if side == "SHORT" and px <= tp1 and not a.get("tp1_hit"):
            a["tp1_hit"] = True
            record_trade({"event":"TP1", "ts":_now_str(), "px":px})
            return "TP1"

        # TP2 / SL
        outcome = None
        if side == "LONG" and px >= tp2:
            outcome = "TP2"
        elif side == "SHORT" and px <= tp2:
            outcome = "TP2"
        elif side == "LONG" and px <= sl:
            outcome = "SL"
        elif side == "SHORT" and px >= sl:
            outcome = "SL"

        if outcome:
            # AI reward + update
            if _AI_OK:
                pnl = (px - entry) if side == "LONG" else (entry - px)
                reward = compute_reward(
                    outcome=outcome, pnl=float(pnl),
                    bars_to_exit=0,
                    tp2_hit=(outcome == "TP2"),
                    tp1_hit=(a.get("tp1_hit", False)),
                    sl_expanded=bool(a.get("expanded", False)),
                    sl_dollars=abs(entry - sl),
                    sl_cap_base=SL_CAP_BASE,
                    trailing_respected=bool(a.get("tp1_hit", False)),
                    momentum_aligned_bars=0,
                    duplicate_entry=False
                )
                feat = {"ema_spread": abs(entry - sl)/max(1.0, entry), "ema_slope": 0.0}
                regime = "trend"
                try:
                    online_update(feat, regime, reward)
                    register_outcome(outcome)
                except Exception:
                    pass

            record_trade({"event": outcome, "ts": _now_str(), "px": px})
            _ACTIVE = None
            return outcome

        return None

def _latest_close(tf="1m"):
    df = _mexc_klines(SYMBOL, tf, limit=2)
    return float(df["close"].iloc[-1])

def start_background(bot):
    """Kick off momentum pings + exit manager loop."""
    def runner():
        global _LAST_PING
        while True:
            time.sleep(PING_INTERVAL_SEC)
            try:
                px = _latest_close("1m")
                outcome = _check_close(px)
                # momentum ping if still open
                with _LOCK:
                    a = _ACTIVE
                if OWNER_CHAT_ID and a is not None:
                    # 5m trend read for context
                    d5 = _mexc_klines(SYMBOL, "5m", 50)
                    d5i = compute_indicators(d5)
                    e9 = float(d5i["ema9"].iloc[-1]); e21=float(d5i["ema21"].iloc[-1])
                    vw = float(d5i["vwap"].iloc[-1])
                    trend = "↑" if (e9>e21 and d5i['close'].iloc[-1]>vw) else ("↓" if (e9<e21 and d5i['close'].iloc[-1]<vw) else "≈")
                    bot.send_message(
                        chat_id=OWNER_CHAT_ID,
                        text=(f"⏱️ Momentum ping\n"
                              f"{a['side']} @ {a['entry']:.2f} | px {px:.2f}\n"
                              f"SL {a['sl']:.2f} TP {a['tp1']:.2f}/{a['tp2']:.2f}\n"
                              f"5m trend: {trend}")
                    )
                if OWNER_CHAT_ID and outcome in ("TP1","TP2","SL"):
                    bot.send_message(chat_id=OWNER_CHAT_ID, text=f"✅ Close: {outcome}")
            except Exception:
                # swallow and continue
                pass

    t = threading.Thread(target=runner, daemon=True)
    t.start()

# ---------- PUBLIC API FOR BOT ----------
def diag_data():
    lines = []
    ok = True
    for tf in ["1m","5m","15m","30m"]:
        try:
            df = _mexc_klines(SYMBOL, tf, 200)
            lines.append(f"{tf}: {len(df)} bars, last={df.index[-1]}")
        except Exception as e:
            ok = False
            lines.append(f"{tf}: FAIL {str(e)[:120]}")
    return "📡 MEXC diag\n" + "\n".join(lines), ("OK" if ok else "ERR")

def get_bot_status():
    with _LOCK:
        a = _ACTIVE
    openline = "none" if a is None else f"{a['side']} @ {a['entry']:.2f} (SL {a['sl']:.2f}, TP {a['tp1']:.2f}/{a['tp2']:.2f})"
    return (f"📊 Current Logic:\n"
            f"- Exchange: MEXC, Symbol: {SYMBOL}\n"
            f"- Entry TF: {PRIMARY_TF}, HTF filter: {FILTER_TF}\n"
            f"- VWAP/EMA + RSI gate, AI≥{AI_THRESHOLD}\n"
            f"- $SL cap {SL_CAP_BASE}→{SL_CAP_MAX} (cushion {SL_CUSHION})\n"
            f"- $TPs {TP1_DOLLARS}/{TP2_DOLLARS}\n"
            f"- Momentum ping: every {PING_INTERVAL_SEC}s\n"
            f"- Open: {openline}")

def get_results():
    rows = _load_logs()
    wins = sum(1 for r in rows if r.get("event") in ("TP1","TP2"))
    tp2  = sum(1 for r in rows if r.get("event") == "TP2")
    sls  = sum(1 for r in rows if r.get("event") == "SL")
    return f"📈 Results: wins {wins} | TP2 {tp2} | SL {sls} | total events {len(rows)}"

def get_trade_logs(limit=30):
    rows = _load_logs()
    view = rows[-limit:]
    parts = []
    for r in view:
        if r.get("event") == "OPEN":
            parts.append(f"OPEN {r.get('side')} @ {r.get('entry'):.2f} (SL {r.get('sl'):.2f}, TP {r.get('tp1'):.2f}/{r.get('tp2'):.2f}) {r.get('ts')}")
        else:
            parts.append(f"{r.get('event')} {r.get('px', '')} {r.get('ts')}")
    return "🧾 Last trades:\n" + "\n".join(parts)

def run_backtest(days=2):
    # 5m bars for last N days
    lim = int((days*24*60)/5) + 10
    d5 = _mexc_klines(SYMBOL, "5m", limit=min(1500, max(200, lim)))
    d15 = _mexc_klines(SYMBOL, "15m", 400)
    d5i = compute_indicators(d5)
    d15i = compute_indicators(d15)

    def htf_ok(idx5):
        t = d5i.index[idx5]
        # nearest 15m <= t
        t15 = d15i.index[d15i.index.get_indexer([t], method="pad")[0]]
        c15 = float(d15i.loc[t15, "close"])
        vw15= float(d15i.loc[t15, "vwap"])
        return (c15 > vw15, c15 < vw15)

    wins=tp2=sl=0
    entries=0
    openpos=None
    lines=[]
    for i in range(25, len(d5i)):
        c = float(d5i["close"].iloc[i]); e9=float(d5i["ema9"].iloc[i]); e21=float(d5i["ema21"].iloc[i])
        vw=float(d5i["vwap"].iloc[i]); rsi=float(d5i["rsi"].iloc[i])
        sp = (e9 - e21) / max(1e-6, c)
        slope = (d5i["ema9"].iloc[i] - d5i["ema9"].iloc[i-3]) / max(1e-6, d5i["ema9"].iloc[i-3])
        # AI score proxy
        score = max(0.0, min(1.0, 0.5 + 0.2*sp + 0.05*slope))
        if openpos is None:
            want_long  = (c>vw and e9>e21 and rsi>45)
            want_short = (c<vw and e9<e21 and rsi<55)
            okL, okS = htf_ok(i)
            side=None
            if want_long and okL and score>=AI_THRESHOLD:
                side="LONG"
            elif want_short and okS and score>=AI_THRESHOLD:
                side="SHORT"
            if side:
                entry=c
                slp = min(SL_CAP_MAX, SL_CAP_BASE+SL_CUSHION)
                if side=="LONG":
                    slv=entry-slp; tp1=entry+TP1_DOLLARS; tp2v=entry+TP2_DOLLARS
                else:
                    slv=entry+slp; tp1=entry-TP1_DOLLARS; tp2v=entry-TP2_DOLLARS
                openpos={"side":side,"entry":entry,"sl":slv,"tp1":tp1,"tp2":tp2v,"tp1_hit":False,"bars":0}
                entries+=1
                lines.append(f"{entries:02d}. {side} @ {entry:.0f} → OPEN in 0 bars")
        else:
            px=c
            side=openpos["side"]
            if side=="LONG":
                if px>=openpos["tp1"] and not openpos["tp1_hit"]:
                    openpos["tp1_hit"]=True
                if px>=openpos["tp2"]:
                    wins+=1; tp2+=1; lines.append(f"{entries:02d}. {side} @ {openpos['entry']:.0f} → TP2 in {openpos['bars']} bars")
                    openpos=None; continue
                if px<=openpos["sl"]:
                    sl+=1; lines.append(f"{entries:02d}. {side} @ {openpos['entry']:.0f} → SL in {openpos['bars']} bars")
                    openpos=None; continue
            else:
                if px<=openpos["tp1"] and not openpos["tp1_hit"]:
                    openpos["tp1_hit"]=True
                if px<=openpos["tp2"]:
                    wins+=1; tp2+=1; lines.append(f"{entries:02d}. {side} @ {openpos['entry']:.0f} → TP2 in {openpos['bars']} bars")
                    openpos=None; continue
                if px>=openpos["sl"]:
                    sl+=1; lines.append(f"{entries:02d}. {side} @ {openpos['entry']:.0f} → SL in {openpos['bars']} bars")
                    openpos=None; continue
            openpos["bars"]+=1

    header=f"🧪 Backtest ({days}d, 5m): {entries} entries | Wins {wins} | TP2 {tp2} | SL {sl}"
    if not entries:
        return header + "\n(no qualifying entries)"
    return header + "\n" + "\n".join(lines[:50])  # clip

def get_ai_status():
    # Show AI persistence knobs if file exists
    path = os.getenv("AI_STATE_FILE", "ai_state.json")
    if os.path.exists(path):
        try:
            data = json.load(open(path,"r"))
            return f"🤖 AI state: streak={data.get('sl_streak')} caution={data.get('caution_multiplier')} explore={data.get('exploration')}"
        except Exception:
            pass
    return "🤖 AI state: default (no file yet)"
