import requests
import pandas as pd
from datetime import datetime
from enum import Enum


class Interval(Enum):
    in_1_minute = '1'
    in_3_minute = '3'
    in_5_minute = '5'
    in_15_minute = '15'
    in_30_minute = '30'
    in_1_hour = '60'
    in_2_hour = '120'
    in_4_hour = '240'
    in_daily = 'D'
    in_weekly = 'W'
    in_monthly = 'M'


class TvDatafeed:
    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password
        self.session = requests.session()
        self.authenticated = self.login()

    def login(self):
        try:
            url = 'https://www.tradingview.com/accounts/signin/'
            headers = {
                'Referer': 'https://www.tradingview.com/',
                'User-Agent': 'Mozilla/5.0'
            }
            payload = {
                'username': self.username,
                'password': self.password,
                'remember': 'on'
            }

            response = self.session.post(url, json=payload, headers=headers)
            if response.status_code == 200 and 'auth_token' in self.session.cookies.get_dict():
                print("✅ TradingView Login successful.")
                return True
            else:
                print(f"❌ Login failed: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Exception during login: {e}")
            return False

    def get_hist(self, symbol, exchange='NSE', interval=Interval.in_1_hour, n_bars=100):
        if not self.authenticated:
            raise Exception("Not authenticated with TradingView")

        try:
            url = 'https://scanner.tradingview.com/america/scan'
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Content-Type': 'application/json'
            }

            payload = {
                "symbols": {"tickers": [f"{exchange}:{symbol}"], "query": {"types": []}},
                "columns": [
                    f"close|{interval.value}",
                    f"open|{interval.value}",
                    f"high|{interval.value}",
                    f"low|{interval.value}",
                    f"volume|{interval.value}"
                ]
            }

            response = self.session.post(url, json=payload, headers=headers)
            data = response.json()

            if not data.get("data"):
                raise Exception("❌ No data returned for symbol.")

            rows = data["data"][0]["d"]
            df = pd.DataFrame([rows], columns=["close", "open", "high", "low", "volume"])

            df["datetime"] = datetime.now()
            df.set_index("datetime", inplace=True)

            return df
        except Exception as e:
            print(f"❌ Failed to fetch historical data: {e}")
            return pd.DataFrame()
