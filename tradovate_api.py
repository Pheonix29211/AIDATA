import requests

class TradovateClient:
    def __init__(self, username, password, client_id="Tradovate", client_secret="abc", demo=True):
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://demo.tradovateapi.com/v1" if demo else "https://live.tradovateapi.com/v1"
        self.token = self.authenticate()

    def authenticate(self):
        url = f"{self.base_url}/auth/accesstokenrequest"
        data = {
            "name": self.username,
            "password": self.password,
            "appId": self.client_id,
            "appVersion": "1.0",
            "cid": self.client_id,
            "sec": self.client_secret
        }
        headers = {"Content-Type": "application/json"}

        response = requests.post(url, headers=headers, json=data)

        try:
            return response.json()['accessToken']
        except KeyError:
            print("❌ Authentication failed.")
            print("Status code:", response.status_code)
            print("Response:", response.text)
            raise SystemExit("⛔ Check your Tradovate username/password or client credentials.")

    def get_market_data(self, symbol):
        url = f"{self.base_url}/md/market-depth/{symbol}"
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(url, headers=headers)
        return response.json()

    def get_contracts(self):
        url = f"{self.base_url}/contract"
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(url, headers=headers)
        return response.json()

    def get_account_info(self):
        url = f"{self.base_url}/account/list"
        headers = {"Authorization": f"Bearer {self.token}"}
        response = requests.get(url, headers=headers)
        return response.json()
