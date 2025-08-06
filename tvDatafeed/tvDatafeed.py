def get_hist(self, symbol, exchange, interval, n_bars):
    tv_symbol = f"{exchange}:{symbol}"
    resolution = interval

    now = int(datetime.now().timestamp())
    from_time = now - int(n_bars) * int(resolution) * 60

    url = f"https://tvd.tradingview.com/history"

    params = {
        "symbol": tv_symbol,
        "resolution": resolution,
        "from": from_time,
        "to": now,
        "countback": n_bars,
    }

    headers = {
        "Referer": "https://www.tradingview.com/",
        "X-Requested-With": "XMLHttpRequest"
    }

    response = self.session.get(url, params=params, headers=headers)

    if response.status_code != 200:
        raise Exception(f"❌ TradingView connection failed with status {response.status_code}")

    data = response.json()

    if data.get("s") != "ok":
        raise Exception("❌ TradingView connection failed")

    df = pd.DataFrame({
        "time": pd.to_datetime(data["t"], unit="s"),
        "open": data["o"],
        "high": data["h"],
        "low": data["l"],
        "close": data["c"],
        "volume": data["v"]
    })

    df.set_index("time", inplace=True)
    return df