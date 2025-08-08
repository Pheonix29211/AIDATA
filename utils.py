import requests
import json
import time
import os
from datetime import datetime, timedelta, timezone

# ===== Utility Functions =====

def _now_ms():
    return int(time.time() * 1000)

def _ms(dt: datetime):
    return int(dt.timestamp() * 1000)

def _two_days_range_ms():
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=2)
    return _ms(start), _ms(end)

# ===== Indicators =====

def _ema_series(values, period):
    ema = []
    k = 2 / (period + 1)
    for i, price in enumerate(values):
        if i == 0:
            ema.append(price)
        else:
            ema.append(price * k + ema[-1] * (1 - k))
    return ema

def _rsi_series(values, period=14):
    gains, losses = [], []
    rsi = []
    for i in range(len(values)):
        if i == 0:
            rsi.append(50)
            continue
        change = values[i] - values[i-1]
        gains.append(max(0, change))
        losses.append(abs(min(0, change)))
        if len(gains) > period:
            gains.pop(0)
            losses.pop(0)
        avg_gain = sum(gains) / period if len(gains) == period else 0
        avg_loss = sum(losses) / period if len(losses) == period else 0
        if avg_loss == 0:
            rsi.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100 - (100 / (1 + rs)))
    return rsi

def _vwap_series(ohlcv, period=20):
    vwap = []
    for i in range(len(ohlcv)):
        if i < period:
            vwap.append(ohlcv[i][4])
        else:
            typical_prices = [sum(ohlcv[j][1:4]) / 3 for j in range(i - period + 1, i + 1)]
            volumes = [ohlcv[j][5] if len(ohlcv[j]) > 5 else 1 for j in range(i - period + 1, i + 1)]
            tpv = sum([typical_prices[k] * volumes[k] for k in range(period)])
            total_vol = sum(volumes)
            vwap.append(tpv / total_vol if total_vol else ohlcv[i][4])
    return vwap

# ===== Data Fetching =====

def get_bybit_history_chunked(total_bars=576, interval="5"):
    url = "https://api.bybit.com/v5/market/kline"
    headers = {"User-Agent": "SpiralBot/1.0"}
    max_limit = 200
    start_ms, end_ms = _two_days_range_ms()

    out = []
    cursor = start_ms
    while cursor < end_ms and len(out) < total_bars:
        params = {
            "category": "linear",
            "symbol": "BTCUSDT",
            "interval": interval,
            "start": cursor,
            "end": end_ms,
            "limit": max_limit
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            j = r.json()
            if r.status_code != 200 or "result" not in j or "list" not in j["result"]:
                break
            chunk = j["result"]["list"]
            if not chunk:
                break
            chunk = list(reversed(chunk))
            out.extend(chunk)
            last_ts_ms = int(chunk[-1][0])
            step_ms = 5 * 60 * 1000 if interval == "5" else 60 * 1000
            cursor = last_ts_ms + step_ms
            time.sleep(0.2)
        except Exception:
            break

    if len(out) > total_bars:
        out = out[-total_bars:]
    return out if out else None

def get_mexc_history_chunked(total_bars=576):
    url = "https://www.mexc.com/open/api/v2/market/kline"
    headers = {"User-Agent": "SpiralBot/1.0"}
    max_limit = 500
    start_ms, end_ms = _two_days_range_ms()

    out = []
    cursor = start_ms
    while cursor < end_ms and len(out) < total_bars:
        params = {
            "symbol": "BTC_USDT",
            "interval": "5m",
            "limit": max_limit,
            "start_time": cursor,
            "end_time": end_ms
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=10)
            j = r.json()
            if r.status_code != 200 or "data" not in j or not isinstance(j["data"], list):
                break
            chunk = j["data"]
            if not chunk:
                break
            out.extend(chunk)
            last_ts_ms = int(chunk[-1][0])
            step_ms = 5 * 60 * 1000
            cursor = last_ts_ms + step_ms
            time.sleep(0.2)
        except Exception:
            break

    if len(out) > total_bars:
        out = out[-total_bars:]
    return out if out else None

def get_history_48h():
    rows = get_bybit_history_chunked(total_bars=576, interval="5")
    if rows:
        return "Bybit", rows
    rows = get_mexc_history_chunked(total_bars=576)
    if rows:
        return "MEXC", rows
    return None, None

# ===== Trade Log Handling =====

TRADE_LOG_FILE = "trade_logs.json"

def load_trade_logs():
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    with open(TRADE_LOG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def save_trade_log(entry):
    logs = load_trade_logs()
    logs.append(entry)
    with open(TRADE_LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

def get_trade_logs():
    return load_trade_logs()[-30:]

def get_results():
    logs = load_trade_logs()
    wins = sum(1 for l in logs if l.get("result") == "win")
    losses = sum(1 for l in logs if l.get("result") == "loss")
    total = wins + losses
    return [wins, losses, total, round((wins / total) * 100, 2) if total > 0 else 0]

# ===== Core Scan =====

def scan_market():
    return [None, "No signal at the moment."]

# ===== Backtest =====

def run_backtest_stream(notify, bars=576):
    source, data = get_history_48h()
    if not data:
        notify("❌ Backtest: unable to fetch history from Bybit or MEXC.")
        return

    def _ohlcv_row(row, source):
        if source == "Bybit":
            return int(row[0])//1000, float(row[1]), float(row[2]), float(row[3]), float(row[4])
        else:
            return int(row[0])//1000, float(row[1]), float(row[2]), float(row[3]), float(row[4])

    ohlcv = [_ohlcv_row(r, source) for r in data]
    closes = [c[4] for c in ohlcv]
    vwap = _vwap_series(ohlcv, period=20)
    ema5 = _ema_series(closes, 5)
    ema20 = _ema_series(closes, 20)
    rsi = _rsi_series(closes, 14)

    notify(f"🧪 Backtest started (~48h) on {source} — pacing 5m per candle.")
    active_trade = None

    for i in range(20, len(ohlcv)):
        price = closes[i]
        if not active_trade:
            if ema5[i] > ema20[i] and rsi[i] < 30:
                active_trade = {"type": "long", "entry": price, "sl": price - 300, "tp": price + 600}
                notify(f"📈 Long entry @ {price}")
            elif ema5[i] < ema20[i] and rsi[i] > 70:
                active_trade = {"type": "short", "entry": price, "sl": price + 300, "tp": price - 600}
                notify(f"📉 Short entry @ {price}")
        else:
            if active_trade["type"] == "long":
                if price >= active_trade["tp"]:
                    notify(f"✅ TP hit @ {price} (+$600)")
                    save_trade_log({"result": "win"})
                    active_trade = None
                elif price <= active_trade["sl"]:
                    notify(f"❌ SL hit @ {price} (-$300)")
                    save_trade_log({"result": "loss"})
                    active_trade = None
            elif active_trade["type"] == "short":
                if price <= active_trade["tp"]:
                    notify(f"✅ TP hit @ {price} (+$600)")
                    save_trade_log({"result": "win"})
                    active_trade = None
                elif price >= active_trade["sl"]:
                    notify(f"❌ SL hit @ {price} (-$300)")
                    save_trade_log({"result": "loss"})
                    active_trade = None
        time.sleep(0.1)
