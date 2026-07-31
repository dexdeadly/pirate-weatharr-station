"""
Pirate Weather API client.

Pirate Weather is a drop-in replacement for the old Dark Sky API, so a single
request returns everything this station needs: current conditions, minute-level
precipitation, 48 (or 168) hourly steps, 7 daily periods, and active NWS alerts.
That is a meaningful simplification over the multi-endpoint NWS flow the
original project used - one call instead of four or more.

The trade-off is quota: Pirate Weather's free tier allows a fixed number of
calls per month, so this client is deliberately conservative:

  * every response is cached with a TTL and served from cache when fresh
  * secondary (regional city) lookups are billed against a separate, slower
    budget than the primary location
  * the ``X-RateLimit-Remaining`` response header is tracked, and the client
    backs off automatically as the monthly budget runs low

API reference: https://pirateweather.net/en/latest/API/
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import requests

#: Pirate Weather API host. Kept as its own constant and asserted below: a
#: package-wide rename once rewrote "pirateweather" to "pws" inside this URL
#: (regex word boundaries treat "." as a break), which silently pointed the
#: client at a non-existent host.
API_HOST = "api.pirateweather.net"
FORECAST_BASE = f"https://{API_HOST}/forecast"

assert API_HOST == "api.pirateweather.net", (
    f"Pirate Weather API host looks corrupted: {API_HOST!r}"
)

#: Blocks we never render, excluded to cut response size and latency.
DEFAULT_EXCLUDE = ("minutely",)

#: Unit systems accepted by the API.
VALID_UNITS = ("us", "si", "ca", "uk")


class PirateWeatherError(RuntimeError):
    """Raised for unrecoverable API problems (bad key, bad coordinates)."""


class RateLimitExceeded(PirateWeatherError):
    """Raised when the monthly quota is exhausted (HTTP 429)."""


class PirateWeatherClient:
    """
    Thread-safe Pirate Weather client with per-URL caching.

    Parameters
    ----------
    api_key:
        Pirate Weather API key.
    lat, lon:
        Primary location in decimal degrees.
    units:
        One of ``us``, ``si``, ``ca``, ``uk``. Defaults to ``us`` (Imperial),
        matching the Dark Sky default.
    cache_ttl:
        Seconds a primary forecast stays fresh. The renderer polls far more
        often than the models actually update, so this is the main quota lever.
    secondary_ttl:
        Longer TTL applied to regional city lookups.
    extend_hourly:
        Request 168 hourly steps instead of 48.
    reserve:
        Stop issuing *secondary* calls once fewer than this many monthly calls
        remain, so the primary location keeps updating.
    """

    def __init__(
        self,
        api_key: str,
        lat: float,
        lon: float,
        *,
        units: str = "us",
        cache_ttl: int = 600,
        secondary_ttl: int = 5400,
        user_agent: str = "PWS/1.0",
        extend_hourly: bool = False,
        timeout: int = 20,
        reserve: int = 750,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise PirateWeatherError(
                "A Pirate Weather API key is required. Create one at "
                "https://pirateweather.net/ and subscribe to the Forecast API."
            )
        self.api_key = key
        self.lat = float(lat)
        self.lon = float(lon)
        self.units = units if units in VALID_UNITS else "us"
        self.ttl = max(60, int(cache_ttl))
        self.secondary_ttl = max(self.ttl, int(secondary_ttl))
        self.user_agent = user_agent
        self.extend_hourly = bool(extend_hourly)
        self.timeout = int(timeout)
        self.reserve = max(0, int(reserve))

        self._lock = threading.RLock()
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._calls_made = 0
        self._quota_limit: Optional[int] = None
        self._quota_remaining: Optional[int] = None
        self._quota_reset: Optional[int] = None
        self._last_error: Optional[str] = None
        self._blocked_until = 0.0

    # -- introspection ----------------------------------------------------

    @property
    def calls_made(self) -> int:
        """Requests actually sent to the API this process lifetime."""
        with self._lock:
            return self._calls_made

    @property
    def quota_remaining(self) -> Optional[int]:
        with self._lock:
            return self._quota_remaining

    @property
    def quota_limit(self) -> Optional[int]:
        with self._lock:
            return self._quota_limit

    @property
    def last_error(self) -> Optional[str]:
        with self._lock:
            return self._last_error

    def quota_summary(self) -> str:
        """Short human-readable quota line for logs / diagnostics."""
        with self._lock:
            if self._quota_remaining is None:
                return f"{self._calls_made} calls sent"
            limit = self._quota_limit
            if limit:
                return f"{self._quota_remaining}/{limit} monthly calls remaining"
            return f"{self._quota_remaining} monthly calls remaining"

    def budget_ok_for_secondary(self) -> bool:
        """Whether there is enough monthly headroom for regional lookups."""
        with self._lock:
            if self._quota_remaining is None:
                return True
            return self._quota_remaining > self.reserve

    # -- HTTP -------------------------------------------------------------

    def _build_url(self, lat: float, lon: float) -> str:
        # The key lives in the path per the API spec. Never log this URL.
        return f"{FORECAST_BASE}/{self.api_key}/{lat:.4f},{lon:.4f}"

    def _params(self) -> Dict[str, str]:
        params = {"units": self.units, "version": "2"}
        if DEFAULT_EXCLUDE:
            params["exclude"] = ",".join(DEFAULT_EXCLUDE)
        if self.extend_hourly:
            params["extend"] = "hourly"
        return params

    def _note_quota(self, headers: Any) -> None:
        def pick(*names: str) -> Optional[int]:
            for name in names:
                raw = headers.get(name)
                if raw is None:
                    continue
                try:
                    return int(float(str(raw).strip()))
                except (TypeError, ValueError):
                    continue
            return None

        limit = pick("X-RateLimit-Limit", "x-ratelimit-limit", "ratelimit-limit")
        remaining = pick("X-RateLimit-Remaining", "x-ratelimit-remaining", "ratelimit-remaining")
        reset = pick("X-RateLimit-Reset", "x-ratelimit-reset", "ratelimit-reset")
        with self._lock:
            if limit is not None:
                self._quota_limit = limit
            if remaining is not None:
                self._quota_remaining = remaining
            if reset is not None:
                self._quota_reset = reset

    def _request(self, lat: float, lon: float) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            if now < self._blocked_until:
                raise RateLimitExceeded(
                    self._last_error or "Pirate Weather quota exhausted; backing off."
                )

        url = self._build_url(lat, lon)
        try:
            resp = requests.get(
                url,
                params=self._params(),
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            with self._lock:
                self._last_error = f"network error: {exc.__class__.__name__}"
            hint = ""
            if "Name or service not known" in str(exc) or "NameResolutionError" in str(exc):
                hint = (f" Could not resolve {API_HOST} - check the container's DNS "
                        f"and outbound network access.")
            raise PirateWeatherError(
                f"Pirate Weather request to {API_HOST} failed: {exc}.{hint}"
            ) from exc

        with self._lock:
            self._calls_made += 1
        self._note_quota(resp.headers)

        if resp.status_code == 429:
            with self._lock:
                self._last_error = "monthly API quota exhausted (HTTP 429)"
                # Back off for an hour rather than hammering the gateway.
                self._blocked_until = time.time() + 3600
            raise RateLimitExceeded(self._last_error)
        if resp.status_code in (401, 403):
            with self._lock:
                self._last_error = "API key rejected (HTTP %d)" % resp.status_code
                self._blocked_until = time.time() + 300
            raise PirateWeatherError(
                "Pirate Weather rejected the API key. Confirm the key is correct "
                "and that you have subscribed to the Forecast API "
                "(activation can take ~20 minutes)."
            )
        if resp.status_code == 400:
            with self._lock:
                self._last_error = "bad request (check latitude/longitude)"
            raise PirateWeatherError(
                "Pirate Weather rejected the coordinates for this location."
            )
        if resp.status_code >= 500:
            with self._lock:
                self._last_error = f"upstream error (HTTP {resp.status_code})"
            raise PirateWeatherError(f"Pirate Weather server error {resp.status_code}")
        if resp.status_code != 200:
            with self._lock:
                self._last_error = f"unexpected HTTP {resp.status_code}"
            raise PirateWeatherError(f"Unexpected Pirate Weather status {resp.status_code}")

        try:
            payload = resp.json()
        except ValueError as exc:
            with self._lock:
                self._last_error = "malformed JSON response"
            raise PirateWeatherError("Pirate Weather returned malformed JSON") from exc

        if not isinstance(payload, dict):
            raise PirateWeatherError("Pirate Weather returned an unexpected payload")

        with self._lock:
            self._last_error = None
            self._blocked_until = 0.0
        return payload

    def _cached(self, lat: float, lon: float, ttl: int) -> Dict[str, Any]:
        cache_key = f"{lat:.3f},{lon:.3f}"
        now = time.time()
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        try:
            payload = self._request(lat, lon)
        except PirateWeatherError:
            # Serve a stale copy rather than blanking the screen.
            with self._lock:
                hit = self._cache.get(cache_key)
            if hit:
                return hit[1]
            raise
        with self._lock:
            self._cache[cache_key] = (time.time(), payload)
        return payload

    # -- public API -------------------------------------------------------

    def forecast(self) -> Dict[str, Any]:
        """Full payload for the primary location (cached for ``cache_ttl``)."""
        return self._cached(self.lat, self.lon, self.ttl)

    def point_forecast(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """
        Payload for a secondary location (regional map cities).

        Returns ``None`` instead of raising, and refuses to spend calls when the
        monthly budget is running low, so the primary feed always wins.
        """
        if not self.budget_ok_for_secondary():
            return None
        try:
            return self._cached(float(lat), float(lon), self.secondary_ttl)
        except PirateWeatherError:
            return None

    # -- convenience accessors -------------------------------------------

    def currently(self) -> Dict[str, Any]:
        return self.forecast().get("currently") or {}

    def hourly(self) -> list[Dict[str, Any]]:
        return (self.forecast().get("hourly") or {}).get("data") or []

    def daily(self) -> list[Dict[str, Any]]:
        return (self.forecast().get("daily") or {}).get("data") or []

    def alerts(self) -> list[Dict[str, Any]]:
        return self.forecast().get("alerts") or []

    def timezone_name(self) -> Optional[str]:
        tz = self.forecast().get("timezone")
        return tz if isinstance(tz, str) and tz else None

    def elevation(self) -> Optional[float]:
        value = self.forecast().get("elevation")
        return float(value) if isinstance(value, (int, float)) else None
