import time
import random

# Dummy values for testing
def generate_trade_signal(client):
    price = client.get_last_price("MNQU5")
    direction = random.choice(["LONG", "SHORT"])
    signal = {
        "id": int(time.time()),
        "entry": price,
        "direction": direction,
        "sl": 15,
        "tp": 45,
        "message": f"🚨 {direction} Signal\nEntry: {price}\nSL: 15 pts | TP: 45 pts"
    }
    return signal

def monitor_trade(client, update, signal):
    entry = signal['entry']
    sl = signal['sl']
    tp = signal['tp']
    direction = signal['direction']
    symbol = "MNQU5"
    trade_id = signal['id']

    while True:
        try:
            price = client.get_last_price(symbol)
            delta = price - entry if direction == "LONG" else entry - price

            if delta >= tp:
                update.message.reply_text(f"✅ TP HIT: +{tp} pts 🎯")
                break
            elif delta >= tp * 0.6:
                update.message.reply_text(f"📈 Trade +{int(delta)} pts – HOLD! Still strong 🚀")
            elif delta <= -sl:
                update.message.reply_text(f"❌ SL HIT: -{sl} pts")
                break
            time.sleep(5)
        except Exception as e:
            update.message.reply_text(f"⚠️ Error monitoring trade: {e}")
            break