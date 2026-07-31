"""
Translate raw Pirate Weather payloads into the flat structures the render
layers consume.

Keeping this conversion in one place means the layers stay presentation-only:
they receive plain dicts of already-formatted strings plus a few raw numbers
for colour ramps and graph scaling.

Pirate Weather returns values in whichever unit system was requested, so this
module carries a small ``Units`` descriptor that supplies the right suffixes and
a Fahrenheit conversion used purely for the temperature colour ramp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any, Iterable, Optional, Sequence

from pws.utils import format_cardinal, safe_round, to_local


# ---------------------------------------------------------------------------
# Unit systems
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Units:
    """Display suffixes for a Pirate Weather unit system."""

    key: str
    temp: str            # degree suffix, e.g. "F"
    wind: str
    pressure: str
    distance: str
    precip_rate: str
    accumulation: str
    metric_temp: bool    # True when temperatures arrive in Celsius


_UNIT_TABLE = {
    "us": Units("us", "F", "mph", "mb", "mi", "in/hr", "in", False),
    "si": Units("si", "C", "m/s", "hPa", "km", "mm/hr", "cm", True),
    "ca": Units("ca", "C", "km/h", "hPa", "km", "mm/hr", "cm", True),
    "uk": Units("uk", "C", "mph", "hPa", "mi", "mm/hr", "cm", True),
}


def units_for(key: str | None) -> Units:
    return _UNIT_TABLE.get((key or "us").strip().lower(), _UNIT_TABLE["us"])


def to_fahrenheit(value: Optional[float], units: Units) -> Optional[float]:
    """Convert a payload temperature to Fahrenheit (for colour mapping only)."""
    if not isinstance(value, (int, float)):
        return None
    return (float(value) * 9.0 / 5.0) + 32.0 if units.metric_temp else float(value)


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    """Coerce to float, treating Pirate Weather's -999 sentinel as missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v <= -998.0:
        return None
    return v


def _deg(value: Optional[float], units: Units, digits: int = 0) -> str:
    v = _num(value)
    if v is None:
        return "--°"
    if digits <= 0:
        return f"{int(round(v))}°"
    return f"{v:.{digits}f}°"


def _deg_unit(value: Optional[float], units: Units) -> str:
    v = _num(value)
    if v is None:
        return f"--°{units.temp}"
    return f"{int(round(v))}°{units.temp}"


def _pct(value: Optional[float]) -> str:
    """Pirate Weather expresses fractions 0-1; render as whole percentages."""
    v = _num(value)
    if v is None:
        return "--"
    return f"{int(round(v * 100))}%"


def _measure(value: Optional[float], suffix: str, digits: int = 1) -> str:
    v = _num(value)
    if v is None:
        return "--"
    if digits <= 0:
        return f"{int(round(v))} {suffix}"
    return f"{v:.{digits}f} {suffix}"


def _local_dt(epoch: Any) -> Optional[datetime]:
    v = _num(epoch)
    if v is None:
        return None
    try:
        return to_local(datetime.fromtimestamp(v, tz=dt_timezone.utc))
    except (OverflowError, OSError, ValueError):
        return None


def _clock(epoch: Any, fmt: str = "%I:%M %p") -> str:
    dt = _local_dt(epoch)
    if not dt:
        return "--"
    return dt.strftime(fmt).lstrip("0")


def _hour_label(epoch: Any) -> str:
    dt = _local_dt(epoch)
    if not dt:
        return ""
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{hour}{dt.strftime('%p')[0]}"


def _is_daytime(icon: Any, epoch: Any = None) -> bool:
    """Pirate Weather encodes day/night in the icon name where relevant."""
    name = str(icon or "")
    if name.endswith("-night"):
        return False
    if name.endswith("-day"):
        return True
    dt = _local_dt(epoch) if epoch is not None else None
    if dt:
        return 6 <= dt.hour < 19
    return True


#: Pirate Weather icon keys that ship with bundled artwork.
_ICON_ASSETS = {
    "clear-day", "clear-night", "rain", "snow", "wind", "fog", "cloudy",
    "partly-cloudy-day", "partly-cloudy-night", "thunderstorm",
}

#: Fallbacks for icon keys with no dedicated asset.
_ICON_ALIASES = {
    "sleet": "snow",
    "hail": "snow",
    "none": "cloudy",
    "": "cloudy",
    "breezy": "wind",
    "windy": "wind",
    "mostly-clear-day": "partly-cloudy-day",
    "mostly-clear-night": "partly-cloudy-night",
    "possible-rain-day": "rain",
    "possible-rain-night": "rain",
    "possible-snow-day": "snow",
    "possible-snow-night": "snow",
    "possible-sleet-day": "snow",
    "possible-sleet-night": "snow",
    "possible-precipitation-day": "rain",
    "possible-precipitation-night": "rain",
    "precipitation": "rain",
    "drizzle": "rain",
    "light-rain": "rain",
    "heavy-rain": "rain",
    "flurries": "snow",
    "light-snow": "snow",
    "heavy-snow": "snow",
    "thunderstorms": "thunderstorm",
    "smoke": "fog",
    "haze": "fog",
    "mist": "fog",
}


def icon_key(raw: Any, is_day: bool = True) -> str:
    """
    Map a Pirate Weather ``icon`` value onto a bundled asset name.

    Unlike the NWS flow - which had to guess an icon by regex-matching English
    forecast prose - Pirate Weather returns a machine-readable icon key
    directly, so this is a lookup rather than a heuristic.
    """
    name = str(raw or "").strip().lower()
    if name in _ICON_ASSETS:
        return name
    alias = _ICON_ALIASES.get(name)
    if alias in _ICON_ASSETS:
        return alias
    # Unknown key: degrade by keyword, then by time of day.
    for token, target in (
        ("thunder", "thunderstorm"), ("snow", "snow"), ("sleet", "snow"),
        ("rain", "rain"), ("drizzle", "rain"), ("fog", "fog"),
        ("wind", "wind"), ("cloud", "cloudy"),
    ):
        if token in name:
            return target
    return "clear-day" if is_day else "clear-night"


def summary_text(raw: Any, fallback: str = "Current conditions") -> str:
    text = str(raw or "").strip()
    if not text:
        return fallback
    # Some payloads echo the icon slug (e.g. "clear-night") as the summary.
    if "-" in text and " " not in text:
        return text.replace("-", " ").title()
    return text


# ---------------------------------------------------------------------------
# Current conditions
# ---------------------------------------------------------------------------

def build_current(payload: dict, units: Units, location_name: str) -> dict:
    """Flatten the ``currently`` block (enriched from ``daily[0]``)."""
    cur = payload.get("currently") or {}
    days = (payload.get("daily") or {}).get("data") or []
    today = days[0] if days else {}

    temp = _num(cur.get("temperature"))
    feels = _num(cur.get("apparentTemperature"))
    icon_raw = cur.get("icon")
    is_day = _is_daytime(icon_raw, cur.get("time"))

    wind_speed = _num(cur.get("windSpeed"))
    gust = _num(cur.get("windGust"))
    wind_dir = format_cardinal(_num(cur.get("windBearing")))
    if wind_speed is None or wind_speed < 0.5:
        wind_display = "Calm"
    else:
        wind_display = f"{wind_dir} {wind_speed:.0f} {units.wind}"
        if gust and gust > wind_speed * 1.3:
            wind_display += f" G{gust:.0f}"

    return {
        "location": location_name,
        "summary": summary_text(cur.get("summary")),
        "icon": icon_key(icon_raw, is_day),
        "is_day": is_day,
        # Raw values for colour ramps / graphs
        "temp": temp,
        "temp_f": to_fahrenheit(temp, units),
        "feels_like": feels,
        # Preformatted display strings
        "temp_display": _deg(temp, units),
        "temp_unit": units.temp,
        "feels_display": _deg_unit(feels, units),
        "dew_display": _deg_unit(cur.get("dewPoint"), units),
        "humidity_display": _pct(cur.get("humidity")),
        "wind_display": wind_display,
        "gust_display": _measure(gust, units.wind, 0),
        "pressure_display": _measure(cur.get("pressure"), units.pressure, 0),
        "visibility_display": _measure(cur.get("visibility"), units.distance, 1),
        "uv_display": (
            f"{_num(cur.get('uvIndex')):.0f}" if _num(cur.get("uvIndex")) is not None else "--"
        ),
        "cloud_display": _pct(cur.get("cloudCover")),
        "precip_prob_display": _pct(cur.get("precipProbability")),
        "precip_type": str(cur.get("precipType") or "none").title(),
        "high_display": _deg(today.get("temperatureHigh"), units),
        "low_display": _deg(today.get("temperatureLow"), units),
        "high_f": to_fahrenheit(_num(today.get("temperatureHigh")), units),
        "low_f": to_fahrenheit(_num(today.get("temperatureLow")), units),
        "sunrise": _clock(today.get("sunriseTime")),
        "sunset": _clock(today.get("sunsetTime")),
        "observed_time": _clock(cur.get("time"), "%I:%M %p"),
    }


# ---------------------------------------------------------------------------
# Hourly
# ---------------------------------------------------------------------------

def build_hourly_points(payload: dict, units: Units, limit: int = 12) -> list[dict]:
    """
    Hourly series for the trend graph.

    Pirate Weather delivers temperature, precipitation probability and cloud
    cover in the same block, so all three graph series come from one call - the
    NWS flow needed a separate gridpoint request just for cloud cover.
    """
    rows = (payload.get("hourly") or {}).get("data") or []
    points: list[dict] = []
    for entry in rows[: max(1, int(limit))]:
        temp = _num(entry.get("temperature"))
        precip = _num(entry.get("precipProbability"))
        cloud = _num(entry.get("cloudCover"))
        points.append(
            {
                "epoch": _num(entry.get("time")),
                "label": _hour_label(entry.get("time")),
                "temp": temp,
                "temp_f": to_fahrenheit(temp, units),
                "precip": None if precip is None else precip * 100.0,
                "cloud": None if cloud is None else cloud * 100.0,
                "icon": icon_key(entry.get("icon"), _is_daytime(entry.get("icon"), entry.get("time"))),
            }
        )
    return points


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------

def build_daily_days(payload: dict, units: Units, limit: int = 7) -> list[dict]:
    """
    Seven-day strip. Day 0 is labelled TODAY.

    Pulls every daily element the API exposes, not just highs and lows - a
    single forecast call already contains humidity, wind, gusts, cloud cover,
    UV, dew point, pressure, visibility, accumulations and sun times, so there
    is no extra quota cost to surfacing them.
    """
    rows = (payload.get("daily") or {}).get("data") or []
    out: list[dict] = []
    for idx, entry in enumerate(rows[: max(1, int(limit))]):
        dt = _local_dt(entry.get("time"))
        if idx == 0:
            name = "TODAY"
        elif dt:
            name = dt.strftime("%a").upper()
        else:
            name = f"DAY {idx + 1}"
        high = _num(entry.get("temperatureHigh"))
        low = _num(entry.get("temperatureLow"))
        precip = _num(entry.get("precipProbability"))
        wind = _num(entry.get("windSpeed"))
        gust = _num(entry.get("windGust"))
        uv = _num(entry.get("uvIndex"))

        precip_type = str(entry.get("precipType") or "").strip().lower()
        if precip_type in ("", "none"):
            precip_type = "precip"

        out.append(
            {
                "name": name,
                "date": dt.strftime("%b %-d") if dt else "",
                # Raw values drive colour ramps and the range bars.
                "high": high,
                "low": low,
                "high_f": to_fahrenheit(high, units),
                "low_f": to_fahrenheit(low, units),
                "unit": units.temp,
                "short": summary_text(entry.get("summary"), ""),
                "icon": icon_key(entry.get("icon"), True),
                "precip": None if precip is None else precip * 100.0,
                "is_day": True,
                # Preformatted secondary elements.
                "precip_type": precip_type,
                "precip_display": _pct(entry.get("precipProbability")),
                "humidity_display": _pct(entry.get("humidity")),
                "wind_display": (
                    "Calm" if wind is None or wind < 0.5
                    else f"{format_cardinal(_num(entry.get('windBearing')))} {wind:.0f}"
                ),
                "wind_unit": units.wind,
                "gust_display": "--" if gust is None else f"{gust:.0f}",
                "cloud_display": _pct(entry.get("cloudCover")),
                "uv_display": "--" if uv is None else f"{uv:.0f}",
                "dew_display": _deg_unit(entry.get("dewPoint"), units),
                "pressure_display": _measure(entry.get("pressure"), units.pressure, 0),
                "visibility_display": _measure(entry.get("visibility"), units.distance, 1),
                "feels_high_display": _deg(entry.get("apparentTemperatureHigh"), units),
                "feels_low_display": _deg(entry.get("apparentTemperatureLow"), units),
                "accumulation_display": _accumulation(entry, units),
                "sunrise": _clock(entry.get("sunriseTime")),
                "sunset": _clock(entry.get("sunsetTime")),
                "moon_phase": moon_phase_name(entry.get("moonPhase")),
            }
        )
    return out


def _accumulation(day: dict, units: Units) -> str:
    """Snow wins over ice wins over liquid, since it is the notable one."""
    for key in ("snowAccumulation", "iceAccumulation", "liquidAccumulation",
                "precipAccumulation"):
        value = _num(day.get(key))
        if value is not None and value > 0.005:
            return _measure(value, units.accumulation, 2)
    return "--"


def build_forecast_periods(payload: dict, units: Units, limit: int = 2) -> list[dict]:
    """Narrative panels for the text-forecast page."""
    rows = (payload.get("daily") or {}).get("data") or []
    out: list[dict] = []
    for idx, entry in enumerate(rows[: max(1, int(limit))]):
        dt = _local_dt(entry.get("time"))
        if idx == 0:
            name = "Today"
        elif idx == 1:
            name = "Tomorrow"
        else:
            name = dt.strftime("%A") if dt else f"Day {idx + 1}"
        wind = _num(entry.get("windSpeed"))
        gust = _num(entry.get("windGust"))
        precip = _num(entry.get("precipProbability"))
        out.append(
            {
                "name": name,
                "high": _deg(entry.get("temperatureHigh"), units),
                "low": _deg(entry.get("temperatureLow"), units),
                "high_f": to_fahrenheit(_num(entry.get("temperatureHigh")), units),
                "unit": units.temp,
                "wind": "--" if wind is None else f"{wind:.0f} {units.wind}",
                "wind_dir": format_cardinal(_num(entry.get("windBearing"))),
                "gust": "--" if gust is None else f"{gust:.0f} {units.wind}",
                "precip": None if precip is None else precip * 100.0,
                "precip_type": (
                    str(entry.get("precipType") or "none").title()
                ),
                "accumulation": _accumulation(entry, units),
                "humidity": _pct(entry.get("humidity")),
                "dew": _deg_unit(entry.get("dewPoint"), units),
                "cloud": _pct(entry.get("cloudCover")),
                "pressure": _measure(entry.get("pressure"), units.pressure, 0),
                "visibility": _measure(entry.get("visibility"), units.distance, 1),
                "feels_high": _deg(entry.get("apparentTemperatureHigh"), units),
                "feels_low": _deg(entry.get("apparentTemperatureLow"), units),
                "uv": (
                    f"{_num(entry.get('uvIndex')):.0f}"
                    if _num(entry.get("uvIndex")) is not None else "--"
                ),
                "moon_phase": moon_phase_name(entry.get("moonPhase")),
                "sunrise": _clock(entry.get("sunriseTime")),
                "sunset": _clock(entry.get("sunsetTime")),
                "short": summary_text(entry.get("summary"), ""),
                "detailed": _narrative(entry, units),
                "icon": icon_key(entry.get("icon"), True),
                "is_day": True,
            }
        )
    return out


def _narrative(day: dict, units: Units) -> str:
    """
    Compose a readable paragraph from daily fields.

    Pirate Weather's ``summary`` is a short phrase rather than the NWS's full
    prose forecast, so we build the longer text ourselves from the numbers.
    """
    parts: list[str] = []
    summary = summary_text(day.get("summary"), "")
    if summary:
        parts.append(summary.rstrip(".") + ".")

    high = _num(day.get("temperatureHigh"))
    low = _num(day.get("temperatureLow"))
    if high is not None and low is not None:
        parts.append(
            f"Highs near {int(round(high))}°{units.temp} with overnight lows "
            f"around {int(round(low))}°{units.temp}."
        )
    elif high is not None:
        parts.append(f"Highs near {int(round(high))}°{units.temp}.")

    precip = _num(day.get("precipProbability"))
    if precip is not None and precip > 0.05:
        ptype = str(day.get("precipType") or "precipitation").lower()
        if ptype in ("none", ""):
            ptype = "precipitation"
        accum = _num(day.get("precipAccumulation"))
        sentence = f"About a {int(round(precip * 100))}% chance of {ptype}"
        if accum and accum > 0.01:
            sentence += f", with up to {accum:.2f} {units.accumulation} possible"
        parts.append(sentence + ".")
    elif precip is not None:
        parts.append("Little to no precipitation expected.")

    wind = _num(day.get("windSpeed"))
    gust = _num(day.get("windGust"))
    if wind is not None:
        cardinal = format_cardinal(_num(day.get("windBearing")))
        sentence = f"Winds {cardinal} near {int(round(wind))} {units.wind}"
        if gust and gust > wind * 1.3:
            sentence += f", gusting to {int(round(gust))} {units.wind}"
        parts.append(sentence + ".")

    humidity = _num(day.get("humidity"))
    dew = _num(day.get("dewPoint"))
    if humidity is not None:
        sentence = f"Humidity around {int(round(humidity * 100))}%"
        if dew is not None:
            sentence += f" with a dew point near {int(round(dew))}°{units.temp}"
        parts.append(sentence + ".")

    cloud = _num(day.get("cloudCover"))
    if cloud is not None:
        pct = int(round(cloud * 100))
        if pct <= 20:
            descriptor = "mostly clear skies"
        elif pct <= 50:
            descriptor = "partly cloudy skies"
        elif pct <= 80:
            descriptor = "mostly cloudy skies"
        else:
            descriptor = "overcast skies"
        parts.append(f"Expect {descriptor} at about {pct}% cloud cover.")

    uv = _num(day.get("uvIndex"))
    if uv is not None and uv >= 6:
        descriptor = "very high" if uv >= 8 else "high"
        parts.append(f"UV index peaking at {int(round(uv))} ({descriptor}); sun protection advised.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Almanac / detail page
# ---------------------------------------------------------------------------

_MOON_PHASES = (
    (0.02, "New Moon"), (0.22, "Waxing Crescent"), (0.28, "First Quarter"),
    (0.47, "Waxing Gibbous"), (0.53, "Full Moon"), (0.72, "Waning Gibbous"),
    (0.78, "Last Quarter"), (0.97, "Waning Crescent"), (1.01, "New Moon"),
)


def moon_phase_name(value: Optional[float]) -> str:
    v = _num(value)
    if v is None:
        return "--"
    for threshold, name in _MOON_PHASES:
        if v <= threshold:
            return name
    return "New Moon"


def build_almanac(payload: dict, units: Units) -> list[dict]:
    """
    Rows for the almanac page.

    This page replaces the reference project's "latest observations" table.
    Pirate Weather is a forecast model rather than a station network, so instead
    of listing nearby METAR readings we surface the richer astronomical and
    air-quality fields that arrive free in the same payload.
    """
    cur = payload.get("currently") or {}
    days = (payload.get("daily") or {}).get("data") or []
    today = days[0] if days else {}

    rows: list[tuple[str, str]] = [
        ("Sunrise", _clock(today.get("sunriseTime"))),
        ("Sunset", _clock(today.get("sunsetTime"))),
        ("Dawn", _clock(today.get("dawnTime"))),
        ("Dusk", _clock(today.get("duskTime"))),
        ("Moon Phase", moon_phase_name(today.get("moonPhase"))),
        ("Dew Point", _deg_unit(cur.get("dewPoint"), units)),
        ("Humidity", _pct(cur.get("humidity"))),
        ("Pressure", _measure(cur.get("pressure"), units.pressure, 0)),
        ("Visibility", _measure(cur.get("visibility"), units.distance, 1)),
        ("Cloud Cover", _pct(cur.get("cloudCover"))),
        ("UV Index", (
            f"{_num(cur.get('uvIndex')):.0f}" if _num(cur.get("uvIndex")) is not None else "--"
        )),
        ("Ozone", _measure(cur.get("ozone"), "DU", 0)),
    ]

    # Version-2 extras: only shown when the API actually returned them.
    liquid = _num(today.get("liquidAccumulation"))
    snow = _num(today.get("snowAccumulation"))
    ice = _num(today.get("iceAccumulation"))
    if liquid is not None:
        rows.append(("Rain Today", _measure(liquid, units.accumulation, 2)))
    if snow is not None and snow > 0:
        rows.append(("Snow Today", _measure(snow, units.accumulation, 2)))
    if ice is not None and ice > 0:
        rows.append(("Ice Today", _measure(ice, units.accumulation, 2)))

    fire = _num(cur.get("fireIndex"))
    if fire is not None:
        rows.append(("Fire Index", f"{fire:.0f}"))
    smoke = _num(cur.get("smoke"))
    if smoke is not None:
        rows.append(("Smoke", _measure(smoke, "µg/m³", 1)))

    elevation = _num(payload.get("elevation"))
    if elevation is not None:
        unit = "ft" if not units.metric_temp else "m"
        shown = elevation * 3.28084 if not units.metric_temp else elevation
        rows.append(("Elevation", f"{int(round(shown))} {unit}"))

    storm = _num(cur.get("nearestStormDistance"))
    if storm is not None:
        rows.append((
            "Nearest Storm",
            "None nearby" if storm <= 0 else _measure(storm, units.distance, 0),
        ))

    return [{"name": name, "value": value} for name, value in rows]


# ---------------------------------------------------------------------------
# Alerts / ticker
# ---------------------------------------------------------------------------

def build_alerts(payload: dict) -> list[dict]:
    """Normalize the ``alerts`` block (US only, sourced from the NWS)."""
    out: list[dict] = []
    for item in payload.get("alerts") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        regions = item.get("regions")
        if isinstance(regions, (list, tuple)):
            region_text = ", ".join(str(r).strip() for r in regions if str(r).strip())
        else:
            region_text = ""
        out.append(
            {
                "title": title,
                "severity": str(item.get("severity") or "Unknown").title(),
                "regions": region_text,
                "expires": _clock(item.get("expires")),
                "description": str(item.get("description") or "").strip(),
            }
        )
    return out


def alerts_ticker_text(alerts: Sequence[dict], limit: int = 6) -> str:
    """Condense alerts into one ticker string."""
    if not alerts:
        return "No active weather alerts"
    chunks = []
    for alert in list(alerts)[: max(1, int(limit))]:
        title = alert.get("title") or ""
        # Alert titles are verbose; keep the leading event phrase.
        headline = title.split(" issued ")[0].strip() or title.strip()
        severity = alert.get("severity") or ""
        if severity and severity.lower() not in ("unknown", ""):
            chunks.append(f"{severity.upper()}: {headline}")
        else:
            chunks.append(headline)
    return "  •  ".join(chunks)


# ---------------------------------------------------------------------------
# Regional / map points
# ---------------------------------------------------------------------------

def build_city_point(name: str, lat: float, lon: float, payload: dict,
                     units: Units) -> Optional[dict]:
    """Marker for one city on the regional map, from that city's payload."""
    cur = (payload or {}).get("currently") or {}
    temp = _num(cur.get("temperature"))
    if temp is None:
        return None
    icon_raw = cur.get("icon")
    is_day = _is_daytime(icon_raw, cur.get("time"))
    return {
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "temp": _deg(temp, units),
        "temp_f": to_fahrenheit(temp, units),
        "condition": summary_text(cur.get("summary"), ""),
        "icon": icon_key(icon_raw, is_day),
        "is_day": is_day,
    }


def build_city_forecast_point(name: str, lat: float, lon: float, payload: dict,
                              units: Units) -> Optional[dict]:
    """Marker for the forecast-map page (tomorrow's high per city)."""
    days = ((payload or {}).get("daily") or {}).get("data") or []
    if not days:
        return None
    day = days[0]
    high = _num(day.get("temperatureHigh"))
    if high is None:
        return None
    return {
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "forecast_temp": _deg(high, units),
        "temp_f": to_fahrenheit(high, units),
        "forecast_short": summary_text(day.get("summary"), ""),
        "icon": icon_key(day.get("icon"), True),
        "is_day": True,
    }
