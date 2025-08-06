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
    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.authenticated = self.login()

    def login(self):
        login_url = "https://www.tradingview.com/accounts/signin/"
        headers = {
            "Referer": "https://www.tradingview.com",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        payload = {
            "username": self.username,
            "password": self.password
        }
        response = self.session.post(login_url, data=payload, headers=headers)
        if response.status_code == 200 and "auth_token" in response.text:
            print("✅ Login successful")
            return True
        else:
            print(f"❌ Login failed: {response.text}")
            return False

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
