"""IP geolocation service with disk cache for peer map display."""

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

# Cache path: ~/.config/beacon/geo_cache.json
CACHE_PATH = Path(
    Path.home() / ".config" / "beacon" / "geo_cache.json"
)

# Cache key for node's own location (from "what's my IP" geo)
MY_LOCATION_KEY = "__my_location__"
MY_LOCATION_TTL = 3600  # Refresh every hour

# Private/local IP patterns - skip lookup
PRIVATE_IP_PATTERN = re.compile(
    r"^(127\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|::1$|fe80:|fc00:|fd00:)"
)


def _is_private_or_local(ip: str) -> bool:
    """Return True if IP is private or local (skip geo lookup)."""
    ip_clean = ip.strip().lower()
    if not ip_clean:
        return True
    if ip_clean in ("localhost", "::1"):
        return True
    return bool(PRIVATE_IP_PATTERN.match(ip_clean))


class GeoCache:
    """IP geolocation with persistent JSON cache."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cache from disk."""
        try:
            if CACHE_PATH.exists():
                self._cache = json.loads(CACHE_PATH.read_text())
        except Exception:
            self._cache = {}

    def _save_cache(self) -> None:
        """Write cache to disk."""
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(self._cache, indent=2))
        except Exception:
            pass

    def _fetch_from_api(self, ip: str) -> dict[str, Any] | None:
        """
        Fetch lat/lon from geo APIs. Returns {lat, lon, country} or None.
        Tries GeoJS, ip-api.com, then ipapi.co. Only successful results are cached;
        failed lookups are retried on the next refresh.
        """
        # GeoJS (primary)
        try:
            r = requests.get(
                f"https://get.geojs.io/v1/ip/geo/{ip}.json",
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            lat = data.get("latitude")
            lon = data.get("longitude")
            country = data.get("country_code") or data.get("country", "")
            if lat is not None and lon is not None:
                return {
                    "lat": float(lat),
                    "lon": float(lon),
                    "country": str(country)[:2] if country else "",
                    "ts": int(time.time()),
                }
        except Exception:
            pass

        # ip-api.com (fallback, 45 req/min)
        try:
            r = requests.get(
                f"http://ip-api.com/json/{ip}?fields=lat,lon,countryCode",
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            lat = data.get("lat")
            lon = data.get("lon")
            country = data.get("countryCode", "")
            if lat is not None and lon is not None:
                return {
                    "lat": float(lat),
                    "lon": float(lon),
                    "country": str(country)[:2] if country else "",
                    "ts": int(time.time()),
                }
        except Exception:
            pass

        # ipapi.co (third fallback, free tier)
        try:
            r = requests.get(
                f"https://ipapi.co/{ip}/json/",
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            lat = data.get("latitude")
            lon = data.get("longitude")
            country = data.get("country_code", "")
            if lat is not None and lon is not None:
                return {
                    "lat": float(lat),
                    "lon": float(lon),
                    "country": str(country)[:2] if country else "",
                    "ts": int(time.time()),
                }
        except Exception:
            pass

        return None

    def lookup(self, ip: str) -> dict[str, Any] | None:
        """
        Look up IP geolocation. Returns {lat, lon, country} or None.
        Skips private IPs. Uses cache; fetches from API on miss.
        Only successful lookups are cached; failed lookups are retried on next refresh.
        """
        ip_clean = ip.strip()
        if not ip_clean:
            return None
        ip_clean = ip_clean.replace("[", "").replace("]", "")
        if _is_private_or_local(ip_clean):
            return None

        if ip_clean in self._cache:
            return self._cache[ip_clean]

        result = self._fetch_from_api(ip_clean)
        if result:
            self._cache[ip_clean] = result
            self._save_cache()
        return result

    def get_my_location(self) -> tuple[float, float] | None:
        """
        Get the node's location (requestor's public IP geo). Cached for MY_LOCATION_TTL.
        Returns (lat, lon) or None if lookup fails.
        """
        now = int(time.time())
        cached = self._cache.get(MY_LOCATION_KEY)
        if cached and (now - cached.get("ts", 0)) < MY_LOCATION_TTL:
            return (cached["lat"], cached["lon"])
        try:
            r = requests.get(
                "https://get.geojs.io/v1/ip/geo.json",
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            lat = data.get("latitude")
            lon = data.get("longitude")
            if lat is not None and lon is not None:
                result = {
                    "lat": float(lat),
                    "lon": float(lon),
                    "country": str(data.get("country_code", ""))[:2],
                    "ts": now,
                }
                self._cache[MY_LOCATION_KEY] = result
                self._save_cache()
                return (result["lat"], result["lon"])
        except Exception:
            pass
        return None
