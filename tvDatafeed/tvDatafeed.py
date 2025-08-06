import requests
import pandas as pd
from datetime import datetime, timedelta

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
            "Content-Type": "application/json"
        }
        payload = {
            "username": self.username,
            "password": self.password
        }
        response = self.session.post(login_url, json=payload, headers=headers)
        if response.status_code == 200 and "auth_token" in response.text:
            print("✅ Login successful")
            return True
        else:
            print(f"❌ Login failed: {response.text}")
            return False

    def get_hist(self, symbol, exchange, interval, n_bars):
        try:
            now = datetime.utcnow()
            times = pd.date_range(end=now, periods=n_bars, freq="1min" if interval == "1" else "5min")
            dummy_data = pd.DataFrame({
                'open': [100 + i for i in range(n_bars)],
                'high': [101 + i for i in range(n_bars)],
                'low': [99 + i for i in range(n_bars)],
                'close': [100 + i for i in range(n_bars)],
                'volume': [1000] * n_bars
            }, index=times)
            return dummy_data
        except Exception as e:
            print("❌ TV connection failed:", str(e))
            return None
