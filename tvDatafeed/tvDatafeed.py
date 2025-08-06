import requests
import pandas as pd
import json
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
        url = "https://www.tradingview.com/accounts/signin/"
        headers = {
            "Referer": "https://www.tradingview.com/",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        payload = {
            "username": self.username,
            "password": self.password
        }
       response = self.session.post(login_url, data=payload, headers=headers)

        try:
            response_data = response.json()
        except Exception:
            print(f"❌ Login failed: Invalid response: {response.text}")
            return False

        if "user" in response_data:
            print("✅ Login successful")
            return True
        else:
            print(f"❌ Login failed: {response_data}")
            return False

    def get_hist(self, symbol, exchange, interval, n_bars):
        # This is still simulated data
        time_index = pd.date_range(end=datetime.now(), periods=n_bars, freq="5min")
        dummy_data = pd.DataFrame({
            'open': [100] * n_bars,
            'high': [105] * n_bars,
            'low': [95] * n_bars,
            'close': [102] * n_bars,
            'volume': [1000] * n_bars
        }, index=time_index)
        return dummy_data
