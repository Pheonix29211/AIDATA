import requests
import pandas as pd
from datetime import datetime

class Interval:
    in_1_minute = "1"
    in_5_minute = "5"
    in_15_minute = "15"
    in_1_hour = "60"
    in_1_day = "1D"
class TvDatafeed:
    def __init__(self, session=None):
        self.session = requests.Session()
        self.authenticated = False

        session_id = session or os.getenv("TV_SESSION")
        if session_id:
            self.session.cookies.set("sessionid", session_id, domain=".tradingview.com")
            print("✅ Session ID set for TradingView")
            self.authenticated = True
        else:
            print("❌ TradingView session ID missing")

    def get_hist(self, symbol, exchange, interval, n_bars):
        try:
            url = f"https://scanner.tradingview.com/{exchange.lower()}/scan"
            # Add correct body if you’re fetching real data
            # Use TradingView WebSocket or scrape for live data if needed (advanced)
            raise Exception("Symbol search skipped (using premium session)")
        except Exception as e:
            print(f"❌ TV connection failed: {str(e)}")
            return None
    def get_hist(self, symbol, exchange, interval, n_bars):
        try:
            url = f"https://scanner.tradingview.com/{exchange.lower()}/scan"
            headers = {
                "Referer": "https://www.tradingview.com",
                "Content-Type": "application/json"
            }
            payload = {
                "symbols": {"tickers": [f"{exchange}:{symbol}"], "query": {"types": []}},
                "columns": [
                    f"open|{interval}",
                    f"high|{interval}",
                    f"low|{interval}",
                    f"close|{interval}",
                    f"volume|{interval}"
                ]
            }

            response = self.session.post(url, json=payload, headers=headers)
            if response.status_code != 200:
                raise Exception("❌ TradingView connection failed")

            data = response.json()
            if "data" not in data or not data["data"]:
                raise Exception("❌ No chart data returned")

            chart_data = data["data"][0]["d"]
            df = pd.DataFrame(chart_data).transpose()
            df.columns = ["open", "high", "low", "close", "volume"]
            df.index = pd.date_range(end=datetime.now(), periods=len(df), freq=f"{interval}min")
            return df

        except Exception as e:
            raise Exception(f"❌ TV connection failed: {str(e)}")
