import os
import logging
from telegram.ext import Updater, CommandHandler
from utils import generate_signal, get_status, get_news_summary
from dotenv import load_dotenv

load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")

def start(update, context):
    update.message.reply_text("🚀 MNQU5 Bot Activated!\nUse /scan to find setups.\nUse /status to view strategy.\nUse /news to get market news.")

def scan(update, context):
    signal = generate_signal()
    update.message.reply_text(signal)

def status(update, context):
    status_msg = get_status()
    update.message.reply_text(status_msg)

def news(update, context):
    news_msg = get_news_summary()
    update.message.reply_text(news_msg)

def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("scan", scan))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("news", news))

    # Use webhook instead of polling
    PORT = int(os.environ.get("PORT", 5000))
    WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}/{BOT_TOKEN}"

    updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=WEBHOOK_URL,
    )
    updater.idle()

if __name__ == '__main__':
    main()