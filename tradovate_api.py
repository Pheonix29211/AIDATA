import requests
import os

class TradovateClient:
    def __init__(self, username, password, demo=True):
        self.username = username
        self.password = password
        self.base_url = "https://demo-api.tradovate.com/v1" if demo else "https://live-api.tradovate.com/v1"
        self.token = self.authenticate()

    def authenticate(self):
        login_url = f"{self.base_url}/auth/accesstokenrequest"
        data = {
            "name": self.username,
            "password": self.password,
            "appId": "MNQBot",
            "appVersion": "1.0",
            "cid": "",
            "sec": "",
            "deviceId": "GPTBot"
        }
        response = requests.post(login_url, json=data)
        response.raise_for_status()
        return response.json()['accessToken']

    def get_last_price(self, symbol="MNQU5"):
        url = f"{self.base_url}/md/lastquote/{symbol}"
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()['price']