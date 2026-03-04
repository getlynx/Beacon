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
        Fetch lat/lon and optional city/region from geo APIs.
        Returns {lat, lon, country, city?, region?, ts} or None.
        Tries GeoJS, ip-api.com, then ipapi.co. Only successful results are cached;
        failed lookups are retried on the next refresh.
        """
        def _norm(s: Any) -> str:
            return str(s).strip() if s else ""

        # GeoJS (primary) - returns city, region
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
                    "city": _norm(data.get("city")),
                    "region": _norm(data.get("region")),
                    "ts": int(time.time()),
                }
        except Exception:
            pass

        # ip-api.com (fallback, 45 req/min) - regionName
        try:
            r = requests.get(
                f"http://ip-api.com/json/{ip}?fields=lat,lon,countryCode,city,regionName",
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
                    "city": _norm(data.get("city")),
                    "region": _norm(data.get("regionName")),
                    "ts": int(time.time()),
                }
        except Exception:
            pass

        # ipapi.co (third fallback, free tier) - city, region
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
                    "city": _norm(data.get("city")),
                    "region": _norm(data.get("region")),
                    "ts": int(time.time()),
                }
        except Exception:
            pass

        return None

    def lookup(self, ip: str, *, force_refresh: bool = False) -> dict[str, Any] | None:
        """
        Look up IP geolocation. Returns {lat, lon, country, city?, region?, ts} or None.
        city and region may be missing on older cache entries. Skips private IPs.
        Uses cache; fetches from API on miss. If force_refresh is True, skips cache
        and fetches from API (e.g. to get city/region for older cache entries).
        """
        ip_clean = ip.strip()
        if not ip_clean:
            return None
        ip_clean = ip_clean.replace("[", "").replace("]", "")
        if _is_private_or_local(ip_clean):
            return None

        if not force_refresh and ip_clean in self._cache:
            return self._cache[ip_clean]

        result = self._fetch_from_api(ip_clean)
        if result:
            self._cache[ip_clean] = result
            self._save_cache()
        return result

    def get_my_location(self, force_refresh: bool = False) -> tuple[float, float] | None:
        """
        Get the node's location (requestor's public IP geo). Cached for MY_LOCATION_TTL.
        Returns (lat, lon) or None if lookup fails. Also caches the node's public IP.
        If force_refresh is True, skip cache and re-fetch (e.g. to populate missing "ip").
        """
        now = int(time.time())
        cached = self._cache.get(MY_LOCATION_KEY)
        if not force_refresh and cached and (now - cached.get("ts", 0)) < MY_LOCATION_TTL:
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
                    "ip": str(data.get("ip", "")).strip(),
                    "ts": now,
                }
                self._cache[MY_LOCATION_KEY] = result
                self._save_cache()
                return (result["lat"], result["lon"])
        except Exception:
            pass
        return None

    def get_my_ip(self) -> str | None:
        """
        Return the node's self-reported public IP (from geo cache). Returns None if unknown.
        Prefers IPv4 when both are available. Kept for backward compatibility.
        """
        ipv4, ipv6 = self.get_my_ipv4_ipv6()
        return ipv4 or ipv6

    def get_my_ipv4_ipv6(self) -> tuple[str | None, str | None]:
        """
        Return the node's self-reported public IPv4 and IPv6.
        Returns (ipv4, ipv6); either can be None if unavailable or fetch failed.
        Results are cached for MY_LOCATION_TTL. Fetches from icanhazip when cache is cold.
        """
        now = int(time.time())
        cached = self._cache.get(MY_LOCATION_KEY)
        if cached and (now - cached.get("ts", 0)) < MY_LOCATION_TTL:
            ipv4 = cached.get("ipv4") or None
            ipv6 = cached.get("ipv6") or None
            if ipv4 is not None or ipv6 is not None:
                return (ipv4, ipv6)
        # Fetch both; use dedicated endpoints so we get v4 and v6 explicitly
        ipv4 = self._fetch_my_ipv4()
        ipv6 = self._fetch_my_ipv6()
        if cached is None:
            cached = {}
        cached = dict(cached)
        cached["ts"] = now
        if ipv4:
            cached["ipv4"] = ipv4
        if ipv6:
            cached["ipv6"] = ipv6
        cached["ip"] = ipv4 or ipv6 or cached.get("ip", "")
        self._cache[MY_LOCATION_KEY] = cached
        self._save_cache()
        return (ipv4, ipv6)

    def _fetch_my_ipv4(self) -> str | None:
        """Fetch node's public IPv4 (plain text)."""
        try:
            r = requests.get("https://ipv4.icanhazip.com", timeout=4)
            r.raise_for_status()
            ip = r.text.strip()
            return ip if ip and not _is_private_or_local(ip) else None
        except Exception:
            return None

    def _fetch_my_ipv6(self) -> str | None:
        """Fetch node's public IPv6 (plain text)."""
        try:
            r = requests.get("https://ipv6.icanhazip.com", timeout=4)
            r.raise_for_status()
            ip = r.text.strip()
            return ip if ip and not _is_private_or_local(ip) else None
        except Exception:
            return None
