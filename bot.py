# bot.py — Telegram webhook, commands, single-trade lock, momentum pings + early-exit
import os, threading, time
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Dispatcher, CommandHandler, CallbackContext
from utils import scan_market, get_trade_logs, get_bot_status, get_results, check_data_source, record_trade, fetch_mexc, compute_indicators

TOKEN = os.getenv("BOT_TOKEN")
OWNER = os.getenv("OWNER_CHAT_ID")
PORT = int(os.getenv("PORT","10000"))
HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME","localhost")

bot = Bot(TOKEN)
app = Flask(__name__)
dp = Dispatcher(bot=bot, update_queue=None, workers=4, use_context=True)

# single-trade lock (in-process)
active_trade = None

def start(update: Update, ctx: CallbackContext):
    update.message.reply_text("🌀 SpiralAI online. Use /menu")

def menu(update: Update, ctx: CallbackContext):
    update.message.reply_text("🌀 Menu:\n/scan\n/forcescan\n/status\n/results\n/logs\n/check")

def scan_cmd(update: Update, ctx: CallbackContext):
    global active_trade
    if active_trade is not None:
        update.message.reply_text("⏳ Trade active; waiting for exit.")
        return
    txt, sig = scan_market()
    update.message.reply_text(txt)
    if sig:
        active_trade = {**sig, "open_price": sig["entry"]}
        threading.Thread(target=_momentum_loop, args=(active_trade.copy(),), daemon=True).start()

def forcescan_cmd(update: Update, ctx: CallbackContext):
    # bypass one-trade lock to just produce a signal text (no thread)
    txt, sig = scan_market()
    update.message.reply_text("📡 Force Scan Result:\n" + txt)

def status_cmd(u,c): u.message.reply_text(get_bot_status())

def results_cmd(u,c):
    n,w,l,net = get_results()
    u.message.reply_text(f"📈 Results: {n} trades | ✅ {w} / ❌ {l} | Net ${net:.2f}")

def logs_cmd(u,c):
    logs = get_trade_logs(20)
    if not logs:
        u.message.reply_text("No trades yet."); 
        return
    lines = []
    for x in logs[-15:]:
        side = x.get('side','').upper()
        en = float(x.get('entry',0))
        pnl = float(x.get('pnl',0))
        t = x.get('time','')[:16].replace('T',' ')
        lines.append(f"{t} {side} @ {en:.2f} PnL {pnl:.2f}")
    msg = "\n".join(lines)
    u.message.reply_text(msg[:4000])

def check_cmd(u,c): u.message.reply_text(check_data_source())

# ---- momentum loop with BE/Trail & early-exit ----
def _momentum_loop(trade):
    global active_trade
    entry = float(trade["entry"])
    side  = trade["side"]
    sl    = float(trade["sl"])
    tp1   = float(trade["tp1"])
    tp2   = float(trade["tp2"])
    chat_id = OWNER
    trail_after = float(os.getenv("TRAIL_AFTER_TP1", "80"))
    early_exit_on = os.getenv("EARLY_EXIT_ENABLE","true").lower()=="true"
    need_5m = os.getenv("EARLY_EXIT_REQUIRE_5M","true").lower()=="true"

    tp1_tagged = False
    be_stop    = sl

    while active_trade is not None and active_trade is trade:
        try:
            df1 = fetch_mexc("1m", limit=60)
            if df1 is None or len(df1) < 25:
                time.sleep(60); 
                continue
            px = float(df1["close"].iloc[-1])
            d1 = compute_indicators(df1).iloc[-1]
            ema_bull_1m = d1["ema9"] > d1["ema21"]
            above_vwap_1m = d1["close"] > d1["vwap"]
            rsi_1m = float(d1["rsi"])

            df5 = fetch_mexc("5m", limit=80)
            d5 = compute_indicators(df5).iloc[-1] if (df5 is not None and len(df5)>30) else None
            ema_bull_5m = (d5["ema9"] > d5["ema21"]) if d5 is not None else None
            above_vwap_5m = (d5["close"] > d5["vwap"]) if d5 is not None else None
            rsi_5m = float(d5["rsi"]) if d5 is not None else None

            if side == "long":
                if not tp1_tagged and px >= tp1:
                    tp1_tagged = True
                    be_stop = max(entry, px - trail_after)
                    bot.send_message(chat_id, f"✅ TP1 @ {px:.2f} — stop to BE / trail ${trail_after}")
                if tp1_tagged:
                    be_stop = max(be_stop, px - trail_after)

                if px <= be_stop:
                    bot.send_message(chat_id, f"❌ Exit @ {px:.2f} (BE/Trail)")
                    record_trade(trade, px - entry); active_trade=None; break
                if px >= tp2:
                    bot.send_message(chat_id, f"🏁 TP2 @ {px:.2f} — closing")
                    record_trade(trade, tp2 - entry); active_trade=None; break

                if early_exit_on:
                    one_min_flip = (not ema_bull_1m) and (not above_vwap_1m)
                    five_min_conf = (d5 is None) or ((not ema_bull_5m) or (rsi_5m is not None and rsi_5m < 50))
                    if one_min_flip and (five_min_conf if need_5m else True):
                        bot.send_message(chat_id, f"⚠️ Momentum weakening — exit @ {px:.2f}")
                        record_trade(trade, px - entry); active_trade=None; break

            else:  # short
                if not tp1_tagged and px <= tp1:
                    tp1_tagged = True
                    be_stop = min(entry, px + trail_after)
                    bot.send_message(chat_id, f"✅ TP1 @ {px:.2f} — stop to BE / trail ${trail_after}")
                if tp1_tagged:
                    be_stop = min(be_stop, px + trail_after)

                if px >= be_stop:
                    bot.send_message(chat_id, f"❌ Exit @ {px:.2f} (BE/Trail)")
                    record_trade(trade, entry - px); active_trade=None; break
                if px <= tp2:
                    bot.send_message(chat_id, f"🏁 TP2 @ {px:.2f} — closing")
                    record_trade(trade, entry - tp2); active_trade=None; break

                if early_exit_on:
                    one_min_flip = (ema_bull_1m) and (above_vwap_1m)
                    five_min_conf = (d5 is None) or (ema_bull_5m or (rsi_5m is not None and rsi_5m > 50))
                    if one_min_flip and (five_min_conf if need_5m else True):
                        bot.send_message(chat_id, f"⚠️ Momentum weakening — exit @ {px:.2f}")
                        record_trade(trade, entry - px); active_trade=None; break

            bot.send_message(chat_id, f"📈 Hold: {side.upper()} px={px:.2f} | BE/Trail={be_stop:.2f} | TP2={tp2:.2f}")
        except Exception:
            pass
        time.sleep(60)

# Handlers
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("menu", menu))
dp.add_handler(CommandHandler("scan", scan_cmd))
dp.add_handler(CommandHandler("forcescan", forcescan_cmd))
dp.add_handler(CommandHandler("status", status_cmd))
dp.add_handler(CommandHandler("results", results_cmd))
dp.add_handler(CommandHandler("logs", logs_cmd))
dp.add_handler(CommandHandler("check", check_cmd))

# Webhook
@app.route(f"/{TOKEN}", methods=["POST"])
def wh():
    update = Update.de_json(request.get_json(force=True), bot)
    dp.process_update(update)
    return "ok"

@app.route("/")
def idx():
    return "🌀 SpiralAI running"

if __name__ == "__main__":
    bot.set_webhook(f"https://{HOST}/{TOKEN}")
    app.run(host="0.0.0.0", port=PORT)
