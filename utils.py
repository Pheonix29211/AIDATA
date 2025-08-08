import requests
import json
import time
import os

TRADE_LOG_FILE = "trade_logs.json"

# ===== Strategy Config =====
BYBIT_SYMBOL = "BTCUSDT"
MEXC_SYMBOL = "BTC_USDT"
RSI_PERIOD = 14
VWAP_PERIOD = 20
TP_RANGE = [600, 1500]   # dollars
SL_LIMIT = 300           # dollars
CONFIDENCE_THRESHOLD = 2.0

# ------- Data fetchers (live) -------

def get_bybit_data(limit=100):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": BYBIT_SYMBOL, "interval": "5", "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=8)
        j = r.json()
        if r.status_code == 200 and "result" in j and "list" in j["result"]:
            return j["result"]["list"]  # newest -> oldest
    except Exception:
        pass
    return None

def get_mexc_data(limit=100):
    url = "https://www.mexc.com/open/api/v2/market/kline"
    params = {"symbol": MEXC_SYMBOL, "interval": "5m", "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=8)
        j = r.json()
        if r.status_code == 200 and "data" in j:
            return j["data"]  # oldest -> newest
    except Exception:
        pass
    return None

def get_chart_data(limit=100):
    data = get_bybit_data(limit=limit)
    if data:
        return "bybit", data
    data = get_mexc_data(limit=limit)
    if data:
        return "mexc", data
    return None, None

# ------- Indicators -------

def _close_list_from_rows(rows, source):
    if source == "bybit":
        # newest -> oldest; flip to oldest -> newest
        rows = list(reversed(rows))
        return [float(x[4]) for x in rows]
    else:
        return [float(x[4]) for x in rows]

def calculate_rsi_from_closes(closes, period=RSI_PERIOD):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_vals = [None]*(period)
    if avg_loss == 0:
        rsi_vals.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_vals.append(100 - (100/(1+rs)))
    for i in range(period+1, len(closes)):
        avg_gain = (avg_gain*(period-1) + gains[i-1]) / period
        avg_loss = (avg_loss*(period-1) + losses[i-1]) / period
        rsi_vals.append(100.0 if avg_loss == 0 else (100 - (100/(1+avg_gain/avg_loss))))
    return rsi_vals[-1]

def get_latest_price(rows, source):
    if source == "bybit":
        # newest row is first
        return float(rows[0][4])
    else:
        # newest is last
        return float(rows[-1][4])

def _ema(closes, period):
    if not closes:
        return None
    k = 2/(period+1)
    ema = closes[0]
    for c in closes[1:]:
        ema = c*k + ema*(1-k)
    return ema

def _ema_pair(closes):
    ema5 = _ema(closes[-50:], 5) if len(closes) >= 5 else None
    ema20 = _ema(closes[-200:], 20) if len(closes) >= 20 else None
    return ema5, ema20

def _vwap_proxy(closes, period=VWAP_PERIOD):
    # Use a simple SMA of closes as a proxy for VWAP trend direction
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def detect_engulfing_from_rows(rows, source):
    # return (bullish, bearish) based on last 2 bars (5m)
    def ohlc(row):
        if source == "bybit":
            return float(row[1]), float(row[2]), float(row[3]), float(row[4])
        else:
            return float(row[1]), float(row[2]), float(row[3]), float(row[4])

    if source == "bybit":
        if len(rows) < 2: return (False, False)
        r2, r1 = rows[0], rows[1]  # newest, prev
    else:
        if len(rows) < 2: return (False, False)
        r2, r1 = rows[-1], rows[-2]

    o1, h1, l1, c1 = ohlc(r1)
    o2, h2, l2, c2 = ohlc(r2)
    bullish = (o1 > c1) and (c2 > o1) and (o2 < c1)
    bearish = (o1 < c1) and (c2 < o1) and (o2 > c1)
    return bullish, bearish

# ------- Trade log helpers (robust to empty/corrupt file) -------

def _ensure_log_file():
    if not os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "w") as f:
            f.write("[]")
        return
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            content = f.read().strip()
        if content == "":
            with open(TRADE_LOG_FILE, "w") as f:
                f.write("[]")
    except Exception:
        with open(TRADE_LOG_FILE, "w") as f:
            f.write("[]")

def save_trade(trade):
    _ensure_log_file()
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = []
    data.append(trade)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(data[-100:], f)

def get_trade_logs():
    _ensure_log_file()
    try:
        with open(TRADE_LOG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def get_results():
    logs = get_trade_logs()
    wins = [t for t in logs if t.get("outcome") == "win"]
    losses = [t for t in logs if t.get("outcome") == "loss"]
    total = len(logs)
    win_rate = round(len(wins)/total*100, 2) if total else 0
    avg_score = round(sum(t.get("score", 0) for t in logs)/total, 2) if total else 0
    return win_rate, len(wins), len(losses), avg_score

# ------- Connectivity -----

def check_data_source():
    source, data = get_chart_data(limit=2)
    if data:
        return f"✅ Connected to {source.upper()}"
    return "❌ Error: Failed to fetch data"

# ------- Live scan (returns (trade_dict_or_None, message)) -------

def scan_market():
    source, rows = get_chart_data(limit=120)
    if not rows:
        return None, "❌ Error: Failed to fetch data"

    closes = _close_list_from_rows(rows, source)
    rsi = calculate_rsi_from_closes(closes, RSI_PERIOD)
    ema5, ema20 = _ema_pair(closes)
    vwap = _vwap_proxy(closes, VWAP_PERIOD)
    price = get_latest_price(rows, source)
    bull_eng, bear_eng = detect_engulfing_from_rows(rows, source)

    if None in (rsi, ema5, ema20, vwap):
        return None, "No signal at the moment."

    trend_up = price > vwap and ema5 and ema20 and ema5 > ema20
    trend_down = price < vwap and ema5 and ema20 and ema5 < ema20

    long_signal = trend_up and rsi < 30 and bull_eng
    short_signal = trend_down and rsi > 70 and bear_eng

    # crude confidence
    score = 0.0
    if long_signal or short_signal:
        score += 1.2
        score += 0.5 if abs(ema5 - ema20) > 5 else 0.0
        score += 0.3 if abs(price - vwap) > 10 else 0.0

    if long_signal or short_signal:
        direction = "long" if long_signal else "short"
        entry = price
        sl = entry - SL_LIMIT if direction == "long" else entry + SL_LIMIT
        tp1 = entry + TP_RANGE[0] if direction == "long" else entry - TP_RANGE[0]
        tp2 = entry + TP_RANGE[1] if direction == "long" else entry - TP_RANGE[1]

        trade = {
            "timestamp": time.time(),
            "type": direction,
            "price": entry,
            "score": round(score, 2),
            "outcome": None
        }
        save_trade(trade)
        msg = (
            f"{'🟢 BUY' if direction=='long' else '🔴 SELL'} Signal\n"
            f"Entry: {entry:.0f}\n"
            f"RSI: {rsi:.1f}  | EMA5{'>' if ema5>ema20 else '<'}EMA20  | VWAP:{'+' if price>vwap else '-'}\n"
            f"SL: {sl:.0f}  TP1: {tp1:.0f}  TP2: {tp2:.0f}\n"
            f"Score: {trade['score']}"
        )
        return trade, msg

    return None, "No signal at the moment."

# ------- Backtest (5m real-time pace) -------

def get_bybit_history(limit=576):
    url = "https://api.bybit.com/v5/market/kline"
    params = {"category": "linear", "symbol": BYBIT_SYMBOL, "interval": "5", "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=8)
        j = r.json()
        if r.status_code == 200 and "result" in j and "list" in j["result"]:
            # newest->oldest; flip to oldest->newest
            return list(reversed(j["result"]["list"]))
    except Exception:
        pass
    return None

def get_mexc_history(limit=576):
    url = "https://www.mexc.com/open/api/v2/market/kline"
    params = {"symbol": MEXC_SYMBOL, "interval": "5m", "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=8)
        j = r.json()
        if r.status_code == 200 and "data" in j:
            # already oldest->newest
            return j["data"]
    except Exception:
        pass
    return None

def _ohlcv_from_row(row, source="bybit"):
    if source == "bybit":
        # [start, open, high, low, close, volume, turnover]
        return int(row[0])//1000, float(row[1]), float(row[2]), float(row[3]), float(row[4])
    else:
        # [ts, open, high, low, close, volume]
        return int(row[0])//1000, float(row[1]), float(row[2]), float(row[3]), float(row[4])

def _vwap_series(ohlcv, period=20):
    vwap = []
    tpv, vol = 0.0, 0.0
    tps = [ (h+l+c)/3.0 for (_,o,h,l,c) in ohlcv ]
    for i, tp in enumerate(tps):
        v = 1.0
        tpv += tp*v
        vol += v
        if i+1 < period:
            vwap.append(None)
        else:
            vwap.append(tpv/vol if vol else tps[i])
            # slide window
            j = i+1 - period
            tpv -= tps[j]*1.0
            vol -= 1.0
    return vwap

def _ema_series(closes, period):
    out = []
    k = 2/(period+1)
    ema = None
    for c in closes:
        ema = c if ema is None else (c*k + ema*(1-k))
        out.append(ema)
    return out

def _rsi_series(closes, period=14):
    out = [None]*len(closes)
    if len(closes) < period+1: return out
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]
        gains.append(max(d,0.0))
        losses.append(max(-d,0.0))
    avg_gain = sum(gains[1:period+1])/period
    avg_loss = sum(losses[1:period+1])/period
    out[period] = 100.0 if avg_loss == 0 else (100 - (100/(1+avg_gain/avg_loss)))
    for i in range(period+1, len(closes)):
        avg_gain = (avg_gain*(period-1)+gains[i])/period
        avg_loss = (avg_loss*(period-1)+losses[i])/period
        out[i] = 100.0 if avg_loss == 0 else (100 - (100/(1+avg_gain/avg_loss)))
    return out

def run_backtest_stream(notify, bars=576):
    data = get_bybit_history(limit=bars)
    source = "Bybit"
    if not data:
        data = get_mexc_history(limit=bars)
        source = "MEXC"
    if not data:
        notify("❌ Backtest: unable to fetch history from Bybit or MEXC.")
        return

    ohlcv = [_ohlcv_from_row(r, "bybit" if source=="Bybit" else "mexc") for r in data]
    closes = [c[4] for c in ohlcv]
    vwap = _vwap_series(ohlcv, period=20)
    ema5 = _ema_series(closes, 5)
    ema20 = _ema_series(closes, 20)
    rsi = _rsi_series(closes, 14)

    active = None
    notify(f"🧪 Backtest started (2 days) on {source} — pacing 5m per candle.")

    for i in range(len(ohlcv)):
        ts, o, h, l, c = ohlcv[i]
        v = vwap[i]
        e5 = ema5[i]
        e20 = ema20[i]
        r = rsi[i]
        if None in (v, e5, e20, r):
            _sleep_5m(); continue

        # manage open trade
        if active:
            if active["dir"] == "LONG":
                sl_hit = l <= active["sl"]
                tp_hit = (h >= active["tp2"]) or (h >= active["tp1"])
            else:
                sl_hit = h >= active["sl"]
                tp_hit = (l <= active["tp2"]) or (l <= active["tp1"])

            if sl_hit:
                save_trade({"timestamp": time.time(), "type": active["dir"].lower(),
                            "price": active["entry"], "score": active["score"], "outcome": "loss"})
                notify(f"❌ SL HIT ({active['dir']}) @ {c:.0f}  | −${SL_LIMIT}")
                active = None
            elif tp_hit:
                realized = TP_RANGE[1] if ((active["dir"]=="LONG" and h>=active["tp2"]) or (active["dir"]=="SHORT" and l<=active["tp2"])) else TP_RANGE[0]
                save_trade({"timestamp": time.time(), "type": active["dir"].lower(),
                            "price": active["entry"], "score": active["score"], "outcome": "win"})
                notify(f"✅ TP HIT ({active['dir']}) @ {c:.0f}  | +${realized}")
                active = None

        # look for new entry if flat
        if not active:
            # engulfing using previous candle
            if i >= 1:
                _, o1,h1,l1,c1 = ohlcv[i-1]
                bullish_engulf = (o1 > c1) and (c > o1) and (o < c1)
                bearish_engulf = (o1 < c1) and (c < o1) and (o > c1)
            else:
                bullish_engulf = bearish_engulf = False

            trend_up = c > v and e5 > e20
            trend_down = c < v and e5 < e20

            long_ok = trend_up and r < 30 and bullish_engulf
            short_ok = trend_down and r > 70 and bearish_engulf

            if long_ok or short_ok:
                direction = "LONG" if long_ok else "SHORT"
                entry = c
                sl = entry - SL_LIMIT if direction=="LONG" else entry + SL_LIMIT
                tp1 = entry + TP_RANGE[0] if direction=="LONG" else entry - TP_RANGE[0]
                tp2 = entry + TP_RANGE[1] if direction=="LONG" else entry - TP_RANGE[1]
                score = 1.0
                active = {"dir": direction, "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "score": score}
                notify(
                    f"{'🟢' if direction=='LONG' else '🔴'} {direction} Signal\n"
                    f"Entry: {entry:.0f}\n"
                    f"SL: {sl:.0f}  TP1: {tp1:.0f}  TP2: {tp2:.0f}\n"
                    f"RSI:{r:.1f}  EMA5{'>' if e5>e20 else '<'}EMA20  VWAP:{'+' if c>v else '-'}"
                )

        _sleep_5m()

    notify("🧪 Backtest finished.")

def _sleep_5m():
    try:
        time.sleep(300)  # exact 5 minutes per 5m bar
    except KeyboardInterrupt:
        pass

