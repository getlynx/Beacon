import os
from typing import Any

import requests


def _float_or_none(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


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
        data = self.fetch_price_data()
        price = data.get("priceUSD")
        return f"${price:.8f}" if price is not None else "-"

    def fetch_price_data(self) -> dict[str, float | None]:
        """Return price data: priceUSD, previousPrice, change24hPct, atomicdex, komodo, frei."""
        result: dict[str, float | None] = {
            "priceUSD": None,
            "previousPrice": None,
            "change24hPct": None,
            "atomicdex": None,
            "komodo": None,
            "frei": None,
        }
        for endpoint in self.endpoints:
            try:
                response = requests.get(endpoint, timeout=3)
                response.raise_for_status()
                raw = response.json()
                d = raw.get("data") or raw
                price_usd = _float_or_none(d.get("priceUSD"))
                prev = _float_or_none(d.get("previousPrice"))
                atomicdex = _float_or_none(d.get("atomicdexPrice"))
                komodo = _float_or_none(d.get("komodoPrice"))
                frei = _float_or_none(d.get("freiExchangePrice"))
                result["priceUSD"] = price_usd
                result["previousPrice"] = prev
                result["atomicdex"] = atomicdex
                result["komodo"] = komodo
                result["frei"] = frei
                if prev and prev != 0 and price_usd is not None:
                    result["change24hPct"] = round((price_usd - prev) / prev * 100, 2)
                return result
            except Exception:
                continue
        return result
