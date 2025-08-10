# utils.py — MEXC-only data (old working style), indicators, AI gate, risk/TP/SL, learning, scan API
import os, time, json, math, re, requests
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from ai_core import score as ai_score, online_update, log_candle_stats

# ===== robust env parsing (tolerate commas/text) =====
def env_float(name, default):
    raw = os.getenv(name, str(default))
    try:
        return float(raw)
    except:
        m = re.search(r'-?\d+(\.\d+)?', raw or "")
        return float(m.group(0)) if m else float(default)

def env_int(name, default):
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except:
        m = re.search(r'-?\d+', raw or "")
        return int(m.group(0)) if m else int(default)

# ==== CONFIG ====
AI_ENABLE = os.getenv("AI_ENABLE","true").lower()=="true"
AI_SCORE_MIN = env_float("AI_SCORE_MIN", 0.65)
TF_LIST = [t.strip() for t in os.getenv("TF_LIST","5m,15m,30m,1h").split(",")]
AI_TF_SWITCH_EDGE = env_float("AI_TF_SWITCH_EDGE", 0.05)

SL_CAP_BASE = env_float("SL_CAP_BASE", 300)
SL_CAP_MAX  = env_float("SL_CAP_MAX", 500)
SL_CUSHION  = env_float("SL_CUSHION_DOLLARS", 50)
AI_ALLOW_SL_EXPAND = os.getenv("AI_ALLOW_SL_EXPAND","true").lower()=="true"
AI_BONUS_EXPAND = env_float("AI_SCORE_BONUS_FOR_SL_EXPAND", 0.10)
TP1_MIN = env_float("TP1_MIN", 300)

FOCUS_ENABLE = os.getenv("FOCUS_ENABLE","true").lower()=="true"
FOCUS_SCORE_BUMP = env_float("FOCUS_SCORE_BUMP", 0.20)
FOCUS_MINUTES = env_int("FOCUS_MINUTES", 30)
FOCUS_COOL_OFF_MIN = env_int("FOCUS_COOL_OFF_MIN", 15)

DAILY_STOP_TRADES = env_int("DAILY_STOP_TRADES", 3)
DAILY_STOP_DOLLARS = env_float("DAILY_STOP_DOLLARS", 900)

COUNTERFACT_LOOKAHEAD = env_int("COUNTERFACT_LOOKAHEAD", 10)
COUNTERFACT_LAMBDA = env_float("COUNTERFACT_LAMBDA", 0.6)

DRY_RUN = os.getenv("DRY_RUN","false").lower()=="true"

# ==== STATE FILES ====
TRADE_LOG_F = Path("trade_logs.json")
if not TRADE_LOG_F.exists(): TRADE_LOG_F.write_text("[]")

active_trade = None
focus_until_ts = 0
losses_today = 0
loss_dollars_today = 0.0
_last_tf = None
last_reset_day = None

# ===== time helpers =====
def _now_utc(): return datetime.now(timezone.utc)
def _day_key(dt): return dt.strftime("%Y-%m-%d")

def reset_if_new_day():
    global losses_today, loss_dollars_today, last_reset_day
    d = _day_key(_now_utc())
    if last_reset_day != d:
        losses_today = 0; loss_dollars_today = 0.0; last_reset_day = d

def _session_from_hour(h):
    if 0 <= h < 7:    return "asia"
    if 7 <= h < 12:   return "london"
    if 12 <= h < 16:  return "overlap"
    if 16 <= h < 20:  return "ny"
    return "late"

# ===== MEXC (EXACT like your old working bot; BTCUSDT spot) =====
MEXC_SYMBOL = "BTCUSDT"

_MEXC_TF_MAP = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "45m": "1h",   # if asked 45m, old bot mapped to 1h
    "1h": "1h",
}
def _mexc_interval(tf: str) -> str:
    return _MEXC_TF_MAP.get(tf, "5m")

def fetch_mexc(tf: str = "5m", limit: int = 1000):
    """
    MEXC v3 klines — same behavior as your old Spiral bot.
    Returns a DataFrame with index=UTC ts and columns: open, high, low, close, volume.
    """
    url = "https://api.mexc.com/api/v3/klines"
    params = {
        "symbol": MEXC_SYMBOL,
        "interval": _mexc_interval(tf),
        "limit": int(limit)
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (SpiralBot)",
        "Accept": "application/json"
    }

    for _ in range(4):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=12)
            if r.status_code != 200:
                time.sleep(0.6); continue
            data = r.json()
            if not isinstance(data, list) or len(data) < 5:
                time.sleep(0.5); continue

            # MEXC array: [ open_time, open, high, low, close, volume, close_time, ... ]
            cols = ["open_time","open","high","low","close","volume"]
            kl = [row[:6] for row in data]
            df = pd.DataFrame(kl, columns=cols)
            for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
            df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df.set_index("ts", inplace=True)
            return df[["open","high","low","close","volume"]]
        except Exception:
            time.sleep(0.6)
    return None

def check_data_source():
    df = fetch_mexc("5m", limit=200)
    return "✅ MEXC OK" if (df is not None and len(df)>0) else "❌ MEXC FAIL"

# ==== INDICATORS ====
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(series, n=14):
    delta = series.diff()
    up = (delta.clip(lower=0)).ewm(alpha=1/n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up/(down+1e-12)
    return 100 - (100/(1+rs))

def atr(df, n=14):
    tr = pd.concat([
        (df["high"]-df["low"]),
        (df["high"]-df["close"].shift()).abs(),
        (df["low"]-df["close"].shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def vwap(df, n=50):
    tp = (df["high"]+df["low"]+df["close"])/3.0
    pv = (tp*df["volume"]).rolling(n).sum()
    vv = df["volume"].rolling(n).sum()
    return pv/(vv+1e-9)

def compute_indicators(df):
    df = df.copy()
    df["ema9"]  = ema(df["close"], 9)
    df["ema21"] = ema(df["close"],21)
    df["ema_slope"]   = (df["ema9"]-df["ema9"].shift(3)) / (abs(df["ema9"].shift(3))+1e-9)
    df["ema_spread"]  = (df["ema9"]-df["ema21"]) / (abs(df["close"])+1e-9)
    df["rsi"] = rsi(df["close"],14)
    df["rsi_slope"] = df["rsi"] - df["rsi"].shift(3)
    df["atr"] = atr(df,14)
    df["atr_pct"] = df["atr"]/(abs(df["close"])+1e-9)
    df["vwap"] = vwap(df,50)
    body = (df["close"]-df["open"]).abs()
    wick = (df["high"]-df["low"]) - body
    df["wick_ratio"] = (wick/(body+1e-9)).clip(0,5)
    df["swing_high"] = df["high"].rolling(10).max()
    df["swing_low"]  = df["low"].rolling(10).min()
    ds_low = (df["close"]-df["swing_low"]).abs()
    ds_high = (df["swing_high"]-df["close"]).abs()
    df["dist_to_swing"] = ds_low.where(ds_low < ds_high, ds_high) / (abs(df["close"])+1e-9)
    flip = ((df["ema9"]>df["ema21"]) != (df["ema9"].shift()>df["ema21"].shift())).astype(int)
    df["ema_flip_count"] = flip.rolling(30).sum().fillna(0)
    return df

def classify_regime(z):
    if z["atr_pct"] > 0.004: return "spike"
    if abs(z["ema_spread"]) > 0.002 and abs(z["ema_slope"])>0.0005: return "trend"
    return "range"

def _sin_cos(val, period):
    ang = 2*math.pi*(val/period)
    return math.sin(ang), math.cos(ang)

def build_features(z, session):
    h = z.name.hour
    hs, hc = _sin_cos(h, 24)
    dow = z.name.weekday()
    ds, dc = _sin_cos(dow, 7)
    return {
        "ema_slope": float(z["ema_slope"]),
        "ema_spread": float(z["ema_spread"]),
        "vwap_dist": float((z["close"]-z["vwap"])/(abs(z["close"])+1e-9)),
        "rsi": (float(z["rsi"])-50.0)/50.0,
        "rsi_slope": float(z["rsi_slope"]/10.0),
        "atr_pct": float(z["atr_pct"]),
        "wick_ratio": float(z["wick_ratio"]/3.0),
        "dist_to_swing": float(z["dist_to_swing"]),
        "ema_flip_count": float(z["ema_flip_count"]/10.0),
        "session_asia": 1.0 if 0<=h<7 else 0.0,
        "session_london":1.0 if 7<=h<12 else 0.0,
        "session_ny":    1.0 if 16<=h<20 else 0.0,
        "session_overlap":1.0 if 12<=h<16 else 0.0,
        "hour_sin": hs, "hour_cos": hc, "dow_sin": ds, "dow_cos": dc
    }

# ==== TF chooser (hysteresis) — MEXC-only ====
def choose_tf():
    global _last_tf
    session = _session_from_hour(_now_utc().hour)
    best = None; best_p = -9; best_row = None
    for tf in TF_LIST:
        df = fetch_mexc(tf, limit=1000)
        if df is None or len(df) < 30:   # tolerant
            continue
        df = compute_indicators(df)
        z = df.iloc[-1]
        regime = classify_regime(z)
        feats = build_features(z, session)
        p,_ = ai_score(feats, regime) if AI_ENABLE else (1.0,0.0)
        if p>best_p:
            best, best_p, best_row = (tf, p, (df,z,regime,feats,session))
    if best is None:
        return None
    if _last_tf is not None and best != _last_tf:
        df2 = fetch_mexc(_last_tf, limit=1000)
        if df2 is not None and len(df2)>=30:
            df2 = compute_indicators(df2)
            z2 = df2.iloc[-1]
            regime2 = classify_regime(z2)
            feats2 = build_features(z2, session)
            p2,_ = ai_score(feats2, regime2) if AI_ENABLE else (1.0,0.0)
            if p2 >= best_p - AI_TF_SWITCH_EDGE:
                return _last_tf, p2, (df2,z2,regime2,feats2,session), "MEXC"
    _last_tf = best
    return best, best_p, best_row, "MEXC"

# ==== Risk / TP / SL planner ====
def plan_risk(z, regime, feats, ai_p):
    price = float(z["close"])
    long_ok = z["ema9"]>z["ema21"] and z["close"]>z["vwap"] and z["rsi"]>50
    short_ok= z["ema9"]<z["ema21"] and z["close"]<z["vwap"] and z["rsi"]<50

    p_thresh = AI_SCORE_MIN
    if FOCUS_ENABLE and time.time() < focus_until_ts:
        p_thresh += FOCUS_SCORE_BUMP

    direction = "long" if long_ok and ai_p>=p_thresh else ("short" if short_ok and ai_p>=p_thresh else None)
    if direction is None: return None

    swing = float(z["swing_low"] if direction=="long" else z["swing_high"])
    sl_struct = (swing - SL_CUSHION) if direction=="long" else (swing + SL_CUSHION)
    sl_dist_d = abs(price - sl_struct)

    allow_expand = (AI_ALLOW_SL_EXPAND and ai_p >= (AI_SCORE_MIN + AI_BONUS_EXPAND)
                    and abs(float(z["ema_spread"]))>0.002 and abs(float(z["rsi_slope"]))>0.5
                    and abs(float((z["close"]-z["vwap"])/(abs(z["close"])+1e-9)))>0.001)
    cap = SL_CAP_MAX if allow_expand else SL_CAP_BASE
    sl_dollars = min(sl_dist_d, cap)

    atr_val = float(z["atr"])
    tp1 = max(TP1_MIN, 0.8*atr_val)
    tp2 = max(tp1*2.0, 1500.0 if regime=="trend" and ai_p>AI_SCORE_MIN+0.15 else tp1*2.2)

    return {
        "direction": direction,
        "entry": price,
        "sl": price - sl_dollars if direction=="long" else price + sl_dollars,
        "tp1": price + tp1 if direction=="long" else price - tp1,
        "tp2": price + tp2 if direction=="long" else price - tp2,
        "ai_allow_expand": allow_expand,
        "ai_p": ai_p,
    }

# ==== Candle learning (no-trade bars) ====
def learn_from_candle(df, z, regime, feats):
    try:
        fwd = df["close"].iloc[-COUNTERFACT_LOOKAHEAD:]
        if len(fwd) <= 1: return
        base = float(df["close"].iloc[-1])
        mfe_up = max(0.0, float(fwd.max())-base)
        mae_up = max(0.0, base - float(fwd.min()))
        reward = max(mfe_up - COUNTERFACT_LOOKAHEAD*COUNTERFACT_LAMBDA, 0.0)
        label = max(0.0, min(1.0, reward/1000.0))
        online_update(feats, regime, label)
        session = "asia"
        if feats.get("session_london")==1.0: session="london"
        elif feats.get("session_ny")==1.0: session="ny"
        elif feats.get("session_overlap")==1.0: session="overlap"
        log_candle_stats(regime, session, reward)
    except Exception:
        pass

# ==== PUBLIC API ====
def scan_market():
    global losses_today, loss_dollars_today
    reset_if_new_day()
    if losses_today>=DAILY_STOP_TRADES or loss_dollars_today<=-DAILY_STOP_DOLLARS:
        return "🛑 Daily stop reached. No new trades.", None

    pick = choose_tf()
    if pick is None: 
        return "ℹ️ No data from MEXC right now.", None
    tf, ai_p, (df,z,regime,feats,session), src = pick

    planned = plan_risk(z, regime, feats, ai_p)
    if planned is None:
        learn_from_candle(df, z, regime, feats)
        return f"ℹ️ No trade | TF {tf} | Regime {regime} | AI {ai_p:.2f}", None

    direction = planned["direction"]; entry=planned["entry"]
    sl=planned["sl"]; tp1=planned["tp1"]; tp2=planned["tp2"]
    exp = " (SL expand)" if planned["ai_allow_expand"] else ""
    txt = (f"{'🟢 LONG' if direction=='long' else '🔴 SHORT'} @ {entry:.2f} | "
           f"SL {sl:.2f} TP {tp1:.2f}→{tp2:.2f} [MEXC]\n"
           f"🧠 AI {ai_p:.2f}{exp} | Regime {regime} | TF {tf}")
    signal = {"side":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tf":tf,"regime":regime,"ai":ai_p,"time":datetime.utcnow().isoformat()+"Z"}
    if DRY_RUN:
        txt = "📝 DRY RUN\n" + txt
        return txt, None
    return txt, signal

def record_trade(trade, outcome_pnl):
    global losses_today, loss_dollars_today
    try:
        logs = json.loads(TRADE_LOG_F.read_text())
    except Exception:
        logs = []
    logs.append({**trade, "pnl": float(outcome_pnl), "closed_at": datetime.utcnow().isoformat()+"Z"})
    TRADE_LOG_F.write_text(json.dumps(logs, indent=2))
    if outcome_pnl < 0:
        losses_today += 1
        loss_dollars_today += outcome_pnl

def get_trade_logs(n=30):
    try:
        logs = json.loads(TRADE_LOG_F.read_text())
        return logs[-n:]
    except Exception:
        return []

def get_bot_status():
    return ("📊 Current Logic:\n"
            f"- Symbol: BTCUSDT (MEXC)\n"
            f"- AI: {'ON' if AI_ENABLE else 'OFF'} | Score min {AI_SCORE_MIN}\n"
            f"- TFs: {', '.join(TF_LIST)} | Switch edge {AI_TF_SWITCH_EDGE}\n"
            f"- Risk: SL ${SL_CAP_BASE} (max {SL_CAP_MAX} if HTF reversal), TP1≥${TP1_MIN}\n"
            f"- Focus: {'ON' if FOCUS_ENABLE else 'OFF'} | Daily stop: "
            f"{DAILY_STOP_TRADES} trades / ${DAILY_STOP_DOLLARS:.0f}\n"
            f"- Dry-run: {'ON' if DRY_RUN else 'OFF'}")

def get_results():
    logs = get_trade_logs(500)
    if not logs: return (0,0,0,0.0)
    wins = sum(1 for x in logs if x.get("pnl",0)>0)
    losses = sum(1 for x in logs if x.get("pnl",0)<=0)
    net = float(sum(x.get("pnl",0) for x in logs))
    return (len(logs), wins, losses, net)
