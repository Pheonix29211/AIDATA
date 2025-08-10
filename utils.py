# utils.py — MEXC data + AI gate + auto management + momentum pings
import os, json, time, random, requests
import pandas as pd
import numpy as np
from datetime import datetime
from ai_core import score as ai_score, online_update, compute_reward, register_outcome

# ---------- ENV ----------
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
TF_LIST = [tf.strip() for tf in os.getenv("TF_LIST", "1m,5m,15m,30m").split(",")]
AI_ENABLE = os.getenv("AI_ENABLE", "true").lower() == "true"
AI_SCORE_MIN = float(os.getenv("AI_SCORE_MIN", "0.50"))
SL_CAP_BASE = float(os.getenv("SL_CAP_BASE", "300"))     # base $300
SL_CAP_MAX  = float(os.getenv("SL_CAP_MAX", "400"))      # expand up to $400
AI_ALLOW_SL_EXPAND = os.getenv("AI_ALLOW_SL_EXPAND","true").lower()=="true"

AUTO_BE     = os.getenv("AUTO_BE", "true").lower()=="true"
AUTO_TRAIL  = os.getenv("AUTO_TRAIL", "true").lower()=="true"
AUTO_EXIT   = os.getenv("AUTO_EXIT", "true").lower()=="true"

OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")  # string
TRADE_LOG = os.getenv("TRADE_LOG", "trade_logs.json")
AI_STATE_FILE = os.getenv("AI_STATE_FILE", "ai_state.json")

# ---------- FILE GUARDS ----------
def _ensure_json_file(path: str):
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write("[]")

_ensure_json_file(TRADE_LOG)
_ensure_json_file(AI_STATE_FILE)

# ---------- OPEN-TRADE STATE (for momentum pings + auto mgmt) ----------
CURRENT_TRADE = {
    "active": False,
    "side": None,         # "long" / "short"
    "entry": None,
    "sl": None,           # planned SL
    "sl_virtual": None,   # auto-managed virtual SL
    "tp1": None,
    "tp2": None,
    "tf": None,
    "opened_at": None,
    "expanded_sl": False,
    "bars_held": 0,
    "moved_be": False,
}

def set_open_trade(plan: dict, tf: str, ts: str):
    CURRENT_TRADE.update({
        "active": True,
        "side": plan["direction"],
        "entry": float(plan["entry"]),
        "sl": float(plan["sl"]),
        "sl_virtual": float(plan["sl"]),
        "tp1": float(plan["tp1"]),
        "tp2": float(plan["tp2"]),
        "tf": tf,
        "opened_at": str(ts),
        "expanded_sl": bool(plan.get("expanded_sl", False)),
        "bars_held": 0,
        "moved_be": False,
    })

def clear_open_trade():
    CURRENT_TRADE.update({
        "active": False, "side": None, "entry": None, "sl": None, "sl_virtual": None,
        "tp1": None, "tp2": None, "tf": None, "opened_at": None, "expanded_sl": False,
        "bars_held": 0, "moved_be": False,
    })

# ---------- LOG ----------
def _append_log(obj: dict):
    try:
        arr = json.load(open(TRADE_LOG, "r"))
    except Exception:
        arr = []
    arr.append(obj)
    json.dump(arr, open(TRADE_LOG, "w"))

def get_trade_logs(limit=30):
    try:
        arr = json.load(open(TRADE_LOG, "r"))
    except Exception:
        return "No logs."
    arr = arr[-limit:]
    lines = []
    for x in arr:
        lines.append(json.dumps(x, ensure_ascii=False))
    return "\n".join(lines)

def get_results():
    try:
        arr = json.load(open(TRADE_LOG, "r"))
    except Exception:
        return "No logs."
    w = sum(1 for x in arr if x.get("outcome") in ("TP1","TP2","EARLY_EXIT"))
    l = sum(1 for x in arr if x.get("outcome") == "SL")
    o = sum(1 for x in arr if x.get("event") == "OPEN")
    return f"W:{w} / L:{l} / OPEN signals:{o}"

def get_bot_status():
    return (
        f"📊 Current Logic:\n"
        f"- {SYMBOL} on MEXC\n"
        f"- TFs: {', '.join(TF_LIST)}\n"
        f"- AI gate: {AI_ENABLE} (min {AI_SCORE_MIN:.2f})\n"
        f"- SL ${SL_CAP_BASE:.0f} (expand to {SL_CAP_MAX:.0f}: {AI_ALLOW_SL_EXPAND})\n"
        f"- TP1 $600 / TP2 $1500\n"
        f"- Auto BE:{AUTO_BE} / Trail:{AUTO_TRAIL} / AutoExit:{AUTO_EXIT}\n"
        f"- Momentum pings: 1m+5m"
    )

# ---------- DATA ----------
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

# ---------- INDICATORS ----------
def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
def _rsi(s, n=14):
    delta = s.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    rs = (up.rolling(n).mean()) / (down.rolling(n).mean().replace(0, np.nan))
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)

def _vwap(df, n=96):  # intraday proxy
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vw = (tp * df["volume"]).rolling(n).sum() / (df["volume"].rolling(n).sum().replace(0, np.nan))
    return vw.fillna(method="bfill").fillna(df["close"])

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema20"] = _ema(out["close"], 20)
    out["ema50"] = _ema(out["close"], 50)
    out["rsi"]   = _rsi(out["close"], 14)
    out["vwap"]  = _vwap(out)
    # helpers
    out["ema_spread"] = (out["ema20"] - out["ema50"]) / out["close"]
    out["ema_slope"]  = out["ema20"].pct_change().rolling(5).mean()
    # engulfing
    o,c = out["open"], out["close"]
    o1,c1 = o.shift(1), c.shift(1)
    out["bull_engulf"] = (c>o) & (o1>c1) & (c>o1) & (o<c1)
    out["bear_engulf"] = (c<o) & (o1<c1) & (c<o1) & (o>c1)
    return out

def _regime(row):
    if row["ema20"]>row["ema50"] and row["close"]>row["vwap"]: return "trend"
    if abs(row["ema_spread"])<0.0015 and abs(row["ema_slope"])<0.0003: return "range"
    return "spike"

# ---------- SIGNAL / PLAN ----------
def _plan_from_row(row, side: str):
    entry = float(row["close"])
    if side == "long":
        sl = entry - SL_CAP_BASE
        tp1 = entry + 600
        tp2 = entry + 1500
    else:
        sl = entry + SL_CAP_BASE
        tp1 = entry - 600
        tp2 = entry - 1500
    return {"direction": side, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "expanded_sl": False}

def _maybe_expand_sl(plan: dict, row_now, row_15=None, row_30=None, ai_p=0.0):
    if not AI_ALLOW_SL_EXPAND: return plan
    if ai_p < max(0.60, AI_SCORE_MIN + 0.05): return plan
    if row_15 is None or row_30 is None: return plan
    # require higher-TF alignment with side
    side = plan["direction"]
    ok15 = (row_15["ema20"]>row_15["ema50"] and row_15["close"]>row_15["vwap"]) if side=="long" else (row_15["ema20"]<row_15["ema50"] and row_15["close"]<row_15["vwap"])
    ok30 = (row_30["ema20"]>row_30["ema50"] and row_30["close"]>row_30["vwap"]) if side=="long" else (row_30["ema20"]<row_30["ema50"] and row_30["close"]<row_30["vwap"])
    if ok15 and ok30:
        # expand to SL_CAP_MAX while keeping direction
        if side=="long":
            plan["sl"] = plan["entry"] - SL_CAP_MAX
        else:
            plan["sl"] = plan["entry"] + SL_CAP_MAX
        plan["expanded_sl"] = True
    return plan

def scan_market():
    """Returns (title, body) or (None, reason). Also sets CURRENT_TRADE for pings."""
    df5 = fetch_mexc("5m", 300)
    if df5 is None or len(df5)<80:
        return (None, "❌ Data Error:\nNo data from MEXC.")
    r5 = compute_indicators(df5).iloc[-1]
    regime = _regime(r5)

    # entry side candidates
    long_ok  = (r5["close"]>r5["vwap"]) and (r5["ema20"]>r5["ema50"]) and (r5["rsi"]<70)
    short_ok = (r5["close"]<r5["vwap"]) and (r5["ema20"]<r5["ema50"]) and (r5["rsi"]>30)

    if not long_ok and not short_ok:
        return ("ℹ️ No trade", f"TF 5m | Regime {regime}")

    # AI gate
    feats = {"ema_spread": float(r5["ema_spread"]), "ema_slope": float(r5["ema_slope"])}
    ai_p, explore = ai_score(feats, regime) if AI_ENABLE else (1.0, 0.0)
    if AI_ENABLE and ai_p < AI_SCORE_MIN and random.random() > explore:
        return ("ℹ️ No trade", f"TF 5m | Regime {regime} | AI {ai_p:.2f}")

    side = "long" if (long_ok and (not short_ok or r5["ema_spread"]>=0)) else "short"
    plan = _plan_from_row(r5, side)

    # consider SL expansion using 15m + 30m
    df15 = fetch_mexc("15m", 300)
    df30 = fetch_mexc("30m", 300)
    if df15 is not None and df30 is not None and len(df15)>30 and len(df30)>30:
        r15 = compute_indicators(df15).iloc[-1]
        r30 = compute_indicators(df30).iloc[-1]
        plan = _maybe_expand_sl(plan, r5, r15, r30, ai_p)

    # register open idea
    set_open_trade(plan, "5m", df5.index[-1].isoformat())

    hdr = f"{'🟢 LONG' if side=='long' else '🔴 SHORT'} @ {plan['entry']:.0f} | SL {plan['sl']:.0f} TP {plan['tp1']:.0f}→{plan['tp2']:.0f} [MEXC]"
    body = f"AI {ai_p:.2f} | Regime {regime} | ExpandedSL {plan['expanded_sl']}"
    _append_log({"ts": time.time(), "event": "OPEN", "side": side, "entry": plan["entry"], "sl": plan["sl"], "tp1": plan["tp1"], "tp2": plan["tp2"], "ai": ai_p, "regime": regime})
    return (hdr, body)

# ---------- MOMENTUM PINGS + AUTO MGMT ----------
def _momo_flags(df_1m: pd.DataFrame, df_5m: pd.DataFrame):
    r1 = compute_indicators(df_1m).iloc[-1]
    r5 = compute_indicators(df_5m).iloc[-1]
    bull1 = (r1["close"]>r1["vwap"]) and (r1["ema20"]>r1["ema50"])
    bear1 = (r1["close"]<r1["vwap"]) and (r1["ema20"]<r1["ema50"])
    bull5 = (r5["close"]>r5["vwap"]) and (r5["ema20"]>r5["ema50"])
    bear5 = (r5["close"]<r5["vwap"]) and (r5["ema20"]<r5["ema50"])
    return r1, r5, bull1, bear1, bull5, bear5

def _close_trade(reason: str, px: float, outcome: str):
    # log + reward
    entry = CURRENT_TRADE["entry"]
    pnl = (px - entry) if CURRENT_TRADE["side"]=="long" else (entry - px)
    bars = CURRENT_TRADE["bars_held"]
    reward = compute_reward(
        outcome=outcome,
        pnl=float(pnl),
        bars_to_exit=int(bars),
        tp2_hit=(outcome=="TP2"),
        tp1_hit=(outcome in ("TP1","TP2")),
        sl_expanded=bool(CURRENT_TRADE.get("expanded_sl", False)),
        sl_dollars=float(abs(CURRENT_TRADE["sl"] - entry)),
        sl_cap_base=SL_CAP_BASE,
        trailing_respected=True,
        momentum_aligned_bars=max(0, bars),
        duplicate_entry=False,
    )
    online_update({"ema_spread":0.0,"ema_slope":0.0}, "trend", reward)
    register_outcome(outcome)
    _append_log({"ts": time.time(), "event":"CLOSE", "reason":reason, "px":px, "pnl":pnl, "outcome":outcome})
    clear_open_trade()
    return pnl

def check_momentum_and_message(bot):
    if not CURRENT_TRADE.get("active"): return
    try:
        d1 = fetch_mexc("1m", 200)
        d5 = fetch_mexc("5m", 200)
        if d1 is None or d5 is None or len(d1)<50 or len(d5)<50: return
        r1, r5, bull1, bear1, bull5, bear5 = _momo_flags(d1, d5)
        last = float(r1["close"])
        side = CURRENT_TRADE["side"]
        entry = CURRENT_TRADE["entry"]
        tp1 = CURRENT_TRADE["tp1"]
        tp2 = CURRENT_TRADE["tp2"]
        slv = CURRENT_TRADE["sl_virtual"]
        CURRENT_TRADE["bars_held"] += 1

        # unrealized
        upnl = (last - entry) if side=="long" else (entry - last)

        # --- AUTO BE ---
        if AUTO_BE and (not CURRENT_TRADE["moved_be"]) and upnl >= 200:
            CURRENT_TRADE["sl_virtual"] = entry
            CURRENT_TRADE["moved_be"] = True
            if OWNER_CHAT_ID:
                bot.send_message(chat_id=OWNER_CHAT_ID, text=f"🔒 BE moved @ {entry:.0f} | uPnL +${upnl:.0f}")

        # --- AUTO TRAIL (VWAP/EMA20 on 1m) ---
        if AUTO_TRAIL:
            if side=="long" and bull1 and bull5:
                trail = max(float(r1["vwap"]), float(r1["ema20"]))
                CURRENT_TRADE["sl_virtual"] = max(CURRENT_TRADE["sl_virtual"], trail)
            elif side=="short" and bear1 and bear5:
                trail = min(float(r1["vwap"]), float(r1["ema20"]))
                CURRENT_TRADE["sl_virtual"] = min(CURRENT_TRADE["sl_virtual"], trail)

        # --- TP checks (auto exit) ---
        if side=="long":
            if last >= tp2:
                _close_trade("TP2", last, "TP2")
                if OWNER_CHAT_ID: bot.send_message(chat_id=OWNER_CHAT_ID, text=f"✅ Trade done: TP2 @ {last:.0f}")
                return
            if last >= tp1:
                # ping to hold if momo strong else book TP1
                if bull1 and bull5:
                    if OWNER_CHAT_ID: bot.send_message(chat_id=OWNER_CHAT_ID, text=f"🎯 TP1 reached {tp1:.0f} — momentum strong, HOLD for TP2")
                else:
                    _close_trade("TP1", last, "TP1")
                    if OWNER_CHAT_ID: bot.send_message(chat_id=OWNER_CHAT_ID, text=f"✅ Trade done: TP1 @ {last:.0f}")
                    return
        else:
            if last <= tp2:
                _close_trade("TP2", last, "TP2")
                if OWNER_CHAT_ID: bot.send_message(chat_id=OWNER_CHAT_ID, text=f"✅ Trade done: TP2 @ {last:.0f}")
                return
            if last <= tp1:
                if bear1 and bear5:
                    if OWNER_CHAT_ID: bot.send_message(chat_id=OWNER_CHAT_ID, text=f"🎯 TP1 reached {tp1:.0f} — momentum strong, HOLD for TP2")
                else:
                    _close_trade("TP1", last, "TP1")
                    if OWNER_CHAT_ID: bot.send_message(chat_id=OWNER_CHAT_ID, text=f"✅ Trade done: TP1 @ {last:.0f}")
                    return

        # --- Auto exit on 5m flip (or SL virtual hit) ---
        flip_against = (side=="long" and bear5) or (side=="short" and bull5)
        sl_hit = (side=="long" and last <= CURRENT_TRADE["sl_virtual"]) or (side=="short" and last >= CURRENT_TRADE["sl_virtual"])
        if AUTO_EXIT and (flip_against or sl_hit):
            reason = "5m flip" if flip_against else "SL/Trail"
            _close_trade(reason, last, "SL" if sl_hit else "EARLY_EXIT")
            if OWNER_CHAT_ID:
                bot.send_message(chat_id=OWNER_CHAT_ID, text=f"🛑 Trade done: {reason} @ {last:.0f}")
            return

        # --- Ping status if still open ---
        if OWNER_CHAT_ID:
            if side=="long":
                msg = f"🟢 HOLD LONG | 1m:{'↑' if bull1 else 'x'} 5m:{'↑' if bull5 else 'x'} | Px {last:.0f} | uPnL +${upnl:.0f} | vSL {CURRENT_TRADE['sl_virtual']:.0f}"
            else:
                msg = f"🔴 HOLD SHORT | 1m:{'↓' if bear1 else 'x'} 5m:{'↓' if bear5 else 'x'} | Px {last:.0f} | uPnL +${upnl:.0f} | vSL {CURRENT_TRADE['sl_virtual']:.0f}"
            bot.send_message(chat_id=OWNER_CHAT_ID, text=msg)

    except Exception:
        return

# ---------- PUBLIC HELPERS FOR BOT ----------
def check_data_source():
    return diag_data()
