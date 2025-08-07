import os
import requests
import time
from datetime import datetime
import json

TRADE_LOG = []

def fetch_price():
    try:
        url = "https://api.bybit.com/v2/public/tickers?symbol=BTCUSDT"
        res = requests.get(url)
        price = float(res.json()['result'][0]['last_price'])
        return price
    except:
        try:
            url = "https://api.mexc.com/api/v3/ticker/price?symbol=BTCUSDT"
            res = requests.get(url)
            return float(res.json()['price'])
        except:
            return None

def scan_market():
    price = fetch_price()
    if not price:
        return "❌ Error: Failed to fetch price"

    rsi = get_rsi()  # placeholder
    vwap_5m = get_vwap("5m")
    vwap_1m = get_vwap("1m")

    signal = ""
    if rsi < 30 and price > vwap_5m:
        signal = f"🚀 BUY Signal\nPrice: {price}\nRSI: {rsi}\nVWAP: {vwap_5m}"
        log_trade("BUY", price, rsi)
    elif rsi > 70 and price < vwap_5m:
        signal = f"🔻 SELL Signal\nPrice: {price}\nRSI: {rsi}\nVWAP: {vwap_5m}"
        log_trade("SELL", price, rsi)

    return signal if signal else "🟡 No clear signal"

def monitor_open_trade(bot, chat_id):
    if not TRADE_LOG:
        return
    trade = TRADE_LOG[-1]
    direction = trade["side"]
    entry = trade["price"]
    while True:
        price = fetch_price()
        if not price:
            continue
        pnl = (price - entry) if direction == "BUY" else (entry - price)
        if pnl * 1 >= 600:
            bot.send_message(chat_id=chat_id, text=f"✅ TP HIT +${pnl:.2f}")
            break
        if pnl * 1 <= -300:
            bot.send_message(chat_id=chat_id, text=f"❌ SL HIT -${pnl:.2f}")
            break
        if check_momentum_shift():
            bot.send_message(chat_id=chat_id, text="⚠️ Momentum Reversal — Consider Exiting")
            break
        bot.send_message(chat_id=chat_id, text=f"📈 Hold: Current PnL: ${pnl:.2f}")
        time.sleep(60)

def log_trade(side, price, rsi):
    TRADE_LOG.append({
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "side": side,
        "price": price,
        "rsi": rsi
    })

def get_recent_trades():
    if not TRADE_LOG:
        return "No trades yet."
    return "\n\n".join(
        [f"{t['time']} | {t['side']} @ {t['price']} | RSI: {t['rsi']}" for t in TRADE_LOG[-30:]]
    )

def get_results():
    return f"✅ Total trades: {len(TRADE_LOG)}"

def get_status():
    return (
        "📊 SpiralBot Logic:\n"
        "- Data: Bybit → MEXC fallback\n"
        "- RSI + VWAP logic\n"
        "- SL: $300 | TP: $600–1500\n"
        "- Monitors 1m + 5m momentum\n"
        "- Sends alerts every 1m post-entry\n"
    )

def get_rsi():
    # Placeholder logic
    return 50

def get_vwap(timeframe):
    # Placeholder logic
    return fetch_price()

def check_momentum_shift():
    # Placeholder logic
    return False