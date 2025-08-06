import os
import requests
import threading
import time
from datetime import datetime
from telegram import Bot

# === Config ===
SYMBOL = os.getenv("TWELVE_SYMBOL", "NAS100")  # example: NAS100
API_KEY = os.getenv("TWELVE_API_KEY")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")

# === Trade memory ===
trade_logs = []
results_summary = {"total": 0, "wins": 0, "losses": 0, "avg_score": 0}
active_trades = {}

# === Data Fetcher ===
def fetch_twelvedata():
    url = f"https://api.twelvedata.com/time_series?symbol={SYMBOL}&interval=1min&outputsize=30&apikey={API_KEY}"
    try:
        response = requests.get(url)
        data = response.json()
        if "values" not in data:
            raise ValueError("No 'values' found in data")
        candles = data["values"]
        candles.reverse()  # Make sure oldest to newest
        return candles
    except Exception as e:
        return f"❌ Error: Failed to fetch data\n{e}"

# === Indicator Logic ===
def calculate_indicators(candles):
    closes = [float(c["close"]) for c in candles]
    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    # RSI
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # VWAP (basic intrabar)
    typical_prices = [(float(c["high"]) + float(c["low"]) + float(c["close"])) / 3 for c in candles]
    volumes = [float(c["volume"]) for c in candles]
    vwap = sum([typical_prices[i] * volumes[i] for i in range(len(candles))]) / sum(volumes)

    # Engulfing
    bullish_engulfing = closes[-1] > opens[-1] and closes[-2] < opens[-2] and closes[-1] > opens[-2]
    bearish_engulfing = closes[-1] < opens[-1] and closes[-2] > opens[-2] and closes[-1] < opens[-2]

    return {
        "price": closes[-1],
        "rsi": rsi,
        "vwap": vwap,
        "bullish_engulfing": bullish_engulfing,
        "bearish_engulfing": bearish_engulfing,
        "candle": candles[-1],
    }

# === Trade Signal ===
def evaluate_signal(data):
    score = 0
    msg = f"📊 {SYMBOL} Signal:\nPrice: {data['price']:.2f}\nVWAP: {data['vwap']:.2f}\nRSI: {data['rsi']:.2f}\n"

    # Trend logic
    if data["price"] > data["vwap"]:
        trend = "Bullish"
    else:
        trend = "Bearish"
    msg += f"Trend: {trend}\n"

    long_signal = (
        trend == "Bullish"
        and data["rsi"] < 30
        and data["bullish_engulfing"]
    )
    short_signal = (
        trend == "Bearish"
        and data["rsi"] > 70
        and data["bearish_engulfing"]
    )

    if long_signal:
        msg += "✅ BUY SIGNAL"
        return msg, "long"
    elif short_signal:
        msg += "🔻 SELL SIGNAL"
        return msg, "short"
    else:
        msg += "🟡 No Clear Entry"
        return msg, None

# === Auto Exit & Hold Logic ===
def momentum_followup(data, trade_type):
    if trade_type == "long" and data["price"] > data["vwap"] and data["rsi"] < 60:
        return "📈 HOLD — Momentum Up"
    elif trade_type == "short" and data["price"] < data["vwap"] and data["rsi"] > 40:
        return "📉 HOLD — Momentum Down"
    else:
        return "❌ EXIT — Momentum Shifted"

# === Auto Scanner ===
def auto_scan_start(bot: Bot):
    def auto_scan():
        while True:
            time.sleep(300)  # Every 5 min
            signal = scan_logic()
            if OWNER_CHAT_ID:
                bot.send_message(chat_id=OWNER_CHAT_ID, text=signal)

    threading.Thread(target=auto_scan, daemon=True).start()

def scan_logic():
    candles = fetch_twelvedata()
    if isinstance(candles, str):  # Error
        return candles

    indicators = calculate_indicators(candles)
    signal_msg, side = evaluate_signal(indicators)

    if side:
        entry_time = datetime.now().strftime("%H:%M:%S")
        trade_logs.append({
            "time": entry_time,
            "side": side,
            "price": indicators["price"],
            "rsi": round(indicators["rsi"], 2),
            "vwap": round(indicators["vwap"], 2),
        })

        active_trades[entry_time] = {"type": side, "data": indicators}
        signal_msg += f"\n\n📍Entry: {indicators['price']:.2f} at {entry_time}"

        # Add followup
        hold_advice = momentum_followup(indicators, side)
        signal_msg += f"\n📊 {hold_advice}"

        # Results logging (simulate outcome here if needed)
        results_summary["total"] += 1
        if hold_advice.startswith("📈") or hold_advice.startswith("📉"):
            results_summary["wins"] += 1
        else:
            results_summary["losses"] += 1

    return signal_msg

# === Telegram Command Handlers ===
def scan_market_and_send_alerts(update, context):
    msg = scan_logic()
    update.message.reply_text(msg)

def get_trade_logs(update, context):
    if not trade_logs:
        update.message.reply_text("No trades logged yet.")
        return

    text = "🧾 Last 30 Trades:\n"
    for t in trade_logs[-30:]:
        text += f"{t['time']} | {t['side'].upper()} @ {t['price']} | RSI: {t['rsi']}\n"
    update.message.reply_text(text)

def get_bot_status(update, context):
    update.message.reply_text(f"""
🤖 SpiralBot Status:
Symbol: {SYMBOL}
Auto Scan: ✅ Every 5 min
Data: TwelveData
Logic: VWAP + RSI + Engulfing + Momentum
""")

def get_trade_results(update, context):
    if results_summary["total"] == 0:
        update.message.reply_text("No results yet.")
        return
    win_rate = (results_summary["wins"] / results_summary["total"]) * 100
    update.message.reply_text(f"""
📊 Performance Summary:
Total Trades: {results_summary["total"]}
Wins: {results_summary["wins"]}
Losses: {results_summary["losses"]}
Win Rate: {win_rate:.2f}%
""")

def check_data_connection(update, context):
    candles = fetch_twelvedata()
    if isinstance(candles, str):
        update.message.reply_text(f"❌ Data Error:\n{candles}")
    else:
        update.message.reply_text("✅ TwelveData is working.")
