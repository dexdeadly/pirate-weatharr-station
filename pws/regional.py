"""
Map-city weather for the Regional Conditions and Forecast Highs pages.

Each map city used to cost one Pirate Weather call per regional refresh (six
cities = six calls, every 90 minutes, per station), so the maps were the
biggest quota consumer after the main forecast. Open-Meteo's forecast API is
free, needs no key and answers for every city in a single request, so the map
cities now come from there. The renderer falls back to Pirate Weather if this
returns nothing.

https://open-meteo.com/en/docs (WMO weather codes: "Weather variable
documentation" table)
"""
from __future__ import annotations

from typing import Optional, Sequence

import requests

from pws import normalize

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

#: WMO weather code -> (summary, day icon, night icon)
_WMO = {
    0: ("Clear", "clear-day", "clear-night"),
    1: ("Mostly Clear", "clear-day", "clear-night"),
    2: ("Partly Cloudy", "partly-cloudy-day", "partly-cloudy-night"),
    3: ("Overcast", "cloudy", "cloudy"),
    45: ("Fog", "fog", "fog"),
    48: ("Freezing Fog", "fog", "fog"),
    51: ("Light Drizzle", "rain", "rain"),
    53: ("Drizzle", "rain", "rain"),
    55: ("Heavy Drizzle", "rain", "rain"),
    56: ("Freezing Drizzle", "sleet", "sleet"),
    57: ("Freezing Drizzle", "sleet", "sleet"),
    61: ("Light Rain", "rain", "rain"),
    63: ("Rain", "rain", "rain"),
    65: ("Heavy Rain", "rain", "rain"),
    66: ("Freezing Rain", "sleet", "sleet"),
    67: ("Freezing Rain", "sleet", "sleet"),
    71: ("Light Snow", "snow", "snow"),
    73: ("Snow", "snow", "snow"),
    75: ("Heavy Snow", "snow", "snow"),
    77: ("Snow Grains", "snow", "snow"),
    80: ("Showers", "rain", "rain"),
    81: ("Showers", "rain", "rain"),
    82: ("Heavy Showers", "rain", "rain"),
    85: ("Snow Showers", "snow", "snow"),
    86: ("Snow Showers", "snow", "snow"),
    95: ("Thunderstorms", "thunderstorm", "thunderstorm"),
    96: ("Thunderstorms", "thunderstorm", "thunderstorm"),
    99: ("Thunderstorms", "thunderstorm", "thunderstorm"),
}


def describe(code, is_day: bool = True) -> tuple[str, str]:
    """(summary, icon key) for a WMO weather code."""
    try:
        summary, day_icon, night_icon = _WMO[int(code)]
    except (KeyError, TypeError, ValueError):
        return ("", "clear-day" if is_day else "clear-night")
    return (summary, day_icon if is_day else night_icon)


def fetch(targets: Sequence[dict], units: "normalize.Units", user_agent: str,
          *, forecast_day: int = 0, timeout: float = 20.0
          ) -> Optional[tuple[list[dict], list[dict]]]:
    """
    Current conditions and a daily high for every target in one request.

    ``forecast_day`` picks which day's high the Forecast Highs page shows
    (0 = today, 1 = tomorrow). Returns ``(current_points, forecast_points)``
    in the shapes normalize.build_city_point / build_city_forecast_point
    produce, or ``None`` if the request failed.
    """
    targets = [t for t in targets if t.get("lat") is not None and t.get("lon") is not None]
    if not targets:
        return [], []
    params = {
        "latitude": ",".join(f"{t['lat']:.4f}" for t in targets),
        "longitude": ",".join(f"{t['lon']:.4f}" for t in targets),
        "current": "temperature_2m,weather_code,is_day",
        "daily": "temperature_2m_max,weather_code",
        "temperature_unit": "celsius" if units.metric_temp else "fahrenheit",
        "timezone": "auto",
        "forecast_days": 2,
    }
    try:
        resp = requests.get(FORECAST_URL, params=params, timeout=timeout,
                            headers={"User-Agent": user_agent})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[regional] Open-Meteo request failed: {exc.__class__.__name__}", flush=True)
        return None
    rows = data if isinstance(data, list) else [data]
    if len(rows) != len(targets):
        return None

    current_points: list[dict] = []
    forecast_points: list[dict] = []
    for target, row in zip(targets, rows):
        cur = (row or {}).get("current") or {}
        temp = normalize._num(cur.get("temperature_2m"))
        is_day = bool(cur.get("is_day", 1))
        if temp is not None:
            summary, icon = describe(cur.get("weather_code"), is_day)
            current_points.append({
                "name": target["name"], "lat": float(target["lat"]), "lon": float(target["lon"]),
                "temp": normalize._deg(temp, units),
                "temp_f": normalize.to_fahrenheit(temp, units),
                "condition": summary, "icon": icon, "is_day": is_day,
            })
        daily = (row or {}).get("daily") or {}
        highs = daily.get("temperature_2m_max") or []
        codes = daily.get("weather_code") or []
        day = min(max(0, forecast_day), len(highs) - 1) if highs else -1
        high = normalize._num(highs[day]) if day >= 0 else None
        if high is not None:
            summary, icon = describe(codes[day] if day < len(codes) else None, True)
            forecast_points.append({
                "name": target["name"], "lat": float(target["lat"]), "lon": float(target["lon"]),
                "forecast_temp": normalize._deg(high, units),
                "temp_f": normalize.to_fahrenheit(high, units),
                "forecast_short": summary, "icon": icon, "is_day": True,
            })
    return current_points, forecast_points
