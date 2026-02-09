import os

import requests


class PricingClient:
    def __init__(self) -> None:
        self.endpoints = [
            os.environ.get(
                "LYNX_PRICE_API_PRIMARY",
                "https://api-one.ewm-cx.info/api/v1/price/getPriceByCoin?symbol=LYNX",
            ),
            os.environ.get(
                "LYNX_PRICE_API_BACKUP",
                "https://api-two.ewm-cx.net/api/v1/price/getPriceByCoin?symbol=LYNX",
            ),
        ]

    def fetch_price_usd(self) -> str:
        for endpoint in self.endpoints:
            try:
                response = requests.get(endpoint, timeout=3)
                response.raise_for_status()
                data = response.json()
                price = data.get("data", {}).get("priceUSD") or data.get("priceUSD")
                if price:
                    return f"${float(price):.8f}"
            except Exception:
                continue
        return "-"
