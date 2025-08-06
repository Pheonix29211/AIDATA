import requests
import pandas as pd
from datetime import datetime, timedelta
import os

class Interval:
    in_1_minute = "1"
    in_5_minute = "5"
    in_15_minute = "15"
    in_1_hour = "60"
    in_1_day = "1D"

class TvDatafeed:
    def __init__(self, session=None):
        self.session = requests.Session()
        self.session_id = session or os.getenv("TV_SESSION")
        if not self.session_id:
            raise Exception("❌ TV_SESSION not set in environment variables")
        self.session.cookies.set("sessionid", self.session_id)
        print("✅ Session ID set for TradingView")

    def get_hist(self, symbol, exchange, interval, n_bars):
        # Build request to TradingView chart history endpoint
        url = "https://www.tradingview.com/chart-data/static/history"

        # Use TradingView-compatible symbol string
        tv_symbol = f"{exchange}:{symbol}"

        params = {
            "symbol": tv_symbol,
            "resolution": interval,
            "from": int((datetime.now() - timedelta(minutes=int(interval)*n_bars)).timestamp()),
            "to": int(datetime.now().timestamp()),
        }

        headers = {
            "Referer": f"https://www.tradingview.com/chart/",
            "X-Requested-With": "XMLHttpRequest",
        }

        response = self.session.get(url, params=params, headers=headers)

        if response.status_code != 200:
            raise Exception(f"❌ TradingView connection failed with status {response.status_code}")

        data = response.json()
        if "s" not in data or data["s"] != "ok":
            raise Exception("❌ TradingView connection failed")

        df = pd.DataFrame({
            "time": pd.to_datetime(data["t"], unit='s'),
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"]
        })

        df.set_index("time", inplace=True)
        return df