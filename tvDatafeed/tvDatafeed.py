import requests
import pandas as pd
import time
from datetime import datetime
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
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.tradingview.com/"
        }

        # Get session ID from environment or argument
        self.session_id = session or os.getenv("TV_SESSION")
        if not self.session_id:
            raise Exception("❌ TV_SESSION not set")

        self.session.cookies.set("sessionid", self.session_id)
        print("✅ Session ID set for TradingView")

    def get_hist(self, symbol, exchange, interval, n_bars):
        tv_symbol = f"{exchange}:{symbol}"

        url = "https://tvd.tradingview.com/history"

        now = int(time.time())
        from_time = now - self._interval_to_seconds(interval) * n_bars

        params = {
            "symbol": tv_symbol,
            "resolution": interval,
            "from": from_time,
            "to": now
        }

        response = self.session.get(url, headers=self.headers, params=params)
        data = response.json()

        if data.get("s") != "ok":
            raise Exception("❌ TradingView connection failed")

        df = pd.DataFrame({
            "time": [datetime.fromtimestamp(t) for t in data["t"]],
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"],
        })

        df.set_index("time", inplace=True)
        return df

    def _interval_to_seconds(self, interval):
        if interval == Interval.in_1_minute:
            return 60
        elif interval == Interval.in_5_minute:
            return 300
        elif interval == Interval.in_15_minute:
            return 900
        elif interval == Interval.in_1_hour:
            return 3600
        elif interval == Interval.in_1_day:
            return 86400
        else:
            raise ValueError("Unsupported interval")