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
        url = f"https://symbol-search.tradingview.com/symbol_search/?text={symbol}&exchange={exchange}"
        resp = self.session.get(url)
        if resp.status_code != 200:
            raise Exception("Symbol search failed")

        # Simulated data for now (replace with TradingView data parsing later)
        time_index = pd.date_range(end=datetime.now(), periods=n_bars, freq="5min")
        dummy_data = pd.DataFrame({
            'open': [100] * n_bars,
            'high': [105] * n_bars,
            'low': [95] * n_bars,
            'close': [102] * n_bars,
            'volume': [1000] * n_bars
        }, index=time_index)
        return dummy_data
