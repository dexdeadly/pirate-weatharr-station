"""
Surf report data: waves and swell, wind at the break, water temperature, tides.

Every source here is free and keyless, so the surf page costs nothing against
the Pirate Weather quota:

  * Open-Meteo Marine API - significant wave height, primary/secondary swell,
    sea-surface temperature; worldwide.  https://open-meteo.com/en/docs/marine-weather-api
  * Open-Meteo Forecast API - 10 m wind and gusts at the spot.
  * NOAA CO-OPS - high/low tide predictions from the nearest tide station; US
    coasts and territories only.  https://api.tidesandcurrents.noaa.gov/api/prod/

Open-Meteo's free tier is for non-commercial use (10,000 calls/day); this
client makes two calls per refresh and refreshes every 30 minutes.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from pws.utils import fmt_time, local_tzinfo

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIDE_STATIONS_URL = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
    "?type=tidepredictions"
)
TIDE_DATA_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

ATTRIBUTION = "Open-Meteo Marine"
TIDE_ATTRIBUTION = "NOAA CO-OPS"

#: Wave/wind models update hourly at best.
MARINE_TTL = 1800
#: Tide predictions are astronomical; a few refreshes a day is plenty.
TIDE_TTL = 6 * 3600
#: The station catalogue essentially never changes.
STATION_TTL = 7 * 24 * 3600
#: Only use a tide station this close to the surf spot.
MAX_TIDE_STATION_MILES = 60.0

_COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def compass(degrees: Any) -> str:
    try:
        value = float(degrees)
    except (TypeError, ValueError):
        return "--"
    return _COMPASS[int((value % 360) / 22.5 + 0.5) % 16]


def _miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _local_now() -> datetime:
    """Naive wall-clock time in the station's timezone (NOAA's lst_ldt times are local)."""
    try:
        return datetime.now(local_tzinfo()).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


class SurfClient:
    """
    Fetches and caches everything the surf page shows for one spot.

    ``units`` follows the station's Pirate Weather unit system: ``us`` and
    ``uk`` report wave height in feet, the metric systems in metres. Wind
    follows the same unit conventions as the rest of the station.
    """

    def __init__(self, lat: float, lon: float, *, units: str = "us",
                 user_agent: str = "PWS/1.0", timeout: float = 15.0) -> None:
        self.lat = float(lat)
        self.lon = float(lon)
        self.units = units if units in ("us", "si", "ca", "uk") else "us"
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}
        self._tide_station: Optional[dict] = None
        self._tide_station_at = 0.0

    # -- plumbing ---------------------------------------------------------

    def _cached(self, key: str, ttl: float, fetch):
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        try:
            value = fetch()
        except Exception as exc:
            print(f"[surf] {key} fetch failed: {exc!r}", flush=True)
            # Serve stale data rather than blanking the page on a blip.
            return hit[1] if hit else None
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def _get_json(self, url: str, params: Optional[dict] = None) -> Any:
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @property
    def imperial_length(self) -> bool:
        return self.units in ("us", "uk")

    # -- sources ----------------------------------------------------------

    def marine(self) -> Optional[dict]:
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            # Snap to the nearest ocean grid cell; a spot pinned on the beach
            # would otherwise land on a land cell and return nothing.
            "cell_selection": "sea",
            "current": ",".join((
                "wave_height", "wave_period", "wave_direction",
                "swell_wave_height", "swell_wave_period", "swell_wave_direction",
                "secondary_swell_wave_height", "secondary_swell_wave_period",
                "secondary_swell_wave_direction", "sea_surface_temperature",
            )),
            "daily": "wave_height_max,swell_wave_period_max,wave_direction_dominant",
            "length_unit": "imperial" if self.imperial_length else "metric",
            "temperature_unit": "fahrenheit" if self.units == "us" else "celsius",
            "timezone": "auto",
            "forecast_days": 5,
        }
        return self._cached("marine", MARINE_TTL,
                            lambda: self._get_json(MARINE_URL, params))

    def wind(self) -> Optional[dict]:
        speed_unit = {"us": "mph", "uk": "mph", "ca": "kmh", "si": "ms"}[self.units]
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "wind_speed_unit": speed_unit,
            "timezone": "auto",
        }
        return self._cached("wind", MARINE_TTL,
                            lambda: self._get_json(FORECAST_URL, params))

    def tide_station(self) -> Optional[dict]:
        """Nearest NOAA tide-prediction station within range, or None."""
        if self._tide_station_at and time.time() - self._tide_station_at < STATION_TTL:
            return self._tide_station
        catalog = self._cached("tide_stations", STATION_TTL,
                               lambda: self._get_json(TIDE_STATIONS_URL))
        best, best_d = None, MAX_TIDE_STATION_MILES
        for st in (catalog or {}).get("stations") or []:
            lat, lon = _num(st.get("lat")), _num(st.get("lng"))
            if lat is None or lon is None:
                continue
            d = _miles(self.lat, self.lon, lat, lon)
            if d < best_d:
                best, best_d = st, d
        if catalog is not None:
            self._tide_station = (
                {"id": str(best.get("id")), "name": str(best.get("name") or "").title(),
                 "miles": best_d}
                if best else None
            )
            self._tide_station_at = time.time()
        return self._tide_station

    def tides(self) -> Optional[dict]:
        station = self.tide_station()
        if not station:
            return None

        def fetch():
            begin = (_local_now() - timedelta(hours=12)).strftime("%Y%m%d %H:%M")
            data = self._get_json(TIDE_DATA_URL, {
                "product": "predictions", "application": "PWS",
                "begin_date": begin, "range": 60, "datum": "MLLW",
                "station": station["id"], "time_zone": "lst_ldt",
                "units": "english" if self.imperial_length else "metric",
                "interval": "hilo", "format": "json",
            })
            if "error" in data:
                raise RuntimeError(data["error"].get("message", "tide API error"))
            return data

        data = self._cached(f"tides:{station['id']}", TIDE_TTL, fetch)
        if not data:
            return None
        return {"station": station, "predictions": data.get("predictions") or []}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

#: Condition tiers, lowest to highest, with the colour key the layer uses.
RATINGS = ("FLAT", "POOR", "FAIR", "GOOD", "EPIC")


def surf_range(wave_height: Optional[float], period: Optional[float]) -> tuple[float, float] | None:
    """
    Estimated breaking-face range from significant wave height and period.

    Long-period groundswell shoals up more than short wind swell of the same
    open-ocean height, so the multiplier grows with period. This is a rule of
    thumb, not a bathymetry-aware forecast - the page labels it "estimated".
    """
    if wave_height is None:
        return None
    p = period if period is not None else 8.0
    factor = max(0.6, min(1.5, 0.5 + 0.06 * p))
    face = wave_height * factor
    return (max(0.0, face * 0.8), face * 1.2)


def rate(face_ft: Optional[float], period: Optional[float],
         wind_mph: Optional[float]) -> str:
    """Coarse conditions rating from size, period and wind strength."""
    if face_ft is None:
        return "--"
    if face_ft < 1.0:
        return "FLAT"
    score = 1 if face_ft < 2 else 2 if face_ft < 3.5 else 3 if face_ft < 7 else 4
    if period is not None:
        if period >= 12:
            score += 1
        elif period < 7:
            score -= 1
    if wind_mph is not None:
        if wind_mph >= 20:
            score -= 2
        elif wind_mph >= 12:
            score -= 1
    return RATINGS[max(1, min(4, score))]


def _to_feet(value: Optional[float], imperial: bool) -> Optional[float]:
    if value is None:
        return None
    return value if imperial else value * 3.28084


def _wind_mph(speed: Optional[float], units: str) -> Optional[float]:
    if speed is None:
        return None
    return {"us": 1.0, "uk": 1.0, "ca": 0.621371, "si": 2.23694}[units] * speed


def _fmt_time(raw: str) -> tuple[str, Optional[datetime]]:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return (raw or "--", None)
    return (fmt_time(dt), dt)


def build_report(client: SurfClient, spot_name: str) -> dict:
    """Fetch everything and shape it for the surf layer. Never raises."""
    imperial = client.imperial_length
    len_unit = "ft" if imperial else "m"
    speed_unit = {"us": "mph", "uk": "mph", "ca": "km/h", "si": "m/s"}[client.units]
    temp_unit = "°F" if client.units == "us" else "°C"

    marine = client.marine() or {}
    current = marine.get("current") or {}
    report: dict[str, Any] = {
        "spot": spot_name,
        "len_unit": len_unit,
        "available": False,
        "source": ATTRIBUTION,
    }

    hs = _num(current.get("wave_height"))
    period = _num(current.get("wave_period"))
    if hs is None:
        report["message"] = "No marine forecast for this spot - check the surf spot coordinates."
        return report
    report["available"] = True

    rng = surf_range(hs, period)
    report["surf_range"] = (
        f"{rng[0]:.0f}-{rng[1]:.0f}" if imperial else f"{rng[0]:.1f}-{rng[1]:.1f}"
    ) if rng else "--"
    report["wave_height"] = f"{hs:.1f} {len_unit}"
    report["wave_period"] = f"{period:.0f}s" if period is not None else "--"
    report["wave_dir"] = compass(current.get("wave_direction"))

    swells = []
    for prefix, label in (("swell_wave", "Primary"), ("secondary_swell_wave", "Secondary")):
        h = _num(current.get(f"{prefix}_height"))
        p = _num(current.get(f"{prefix}_period"))
        d = _num(current.get(f"{prefix}_direction"))
        if h is None or h <= 0:
            continue
        swells.append({
            "label": label,
            "height": f"{h:.1f} {len_unit}",
            "period": f"{p:.0f}s" if p is not None else "--",
            "dir": compass(d),
            "deg": d,
        })
    report["swells"] = swells

    sst = _num(current.get("sea_surface_temperature"))
    report["water_temp"] = f"{sst:.0f}{temp_unit}" if sst is not None else "--"

    wind = (client.wind() or {}).get("current") or {}
    w_speed = _num(wind.get("wind_speed_10m"))
    w_gust = _num(wind.get("wind_gusts_10m"))
    report["wind"] = (
        f"{compass(wind.get('wind_direction_10m'))} {w_speed:.0f} {speed_unit}"
        if w_speed is not None else "--"
    )
    report["wind_gust"] = f"G {w_gust:.0f}" if w_gust is not None else ""

    face_ft = _to_feet(rng[1], imperial) if rng else None
    report["rating"] = rate(face_ft, period, _wind_mph(w_speed, client.units))

    daily = marine.get("daily") or {}
    outlook = []
    for i, day in enumerate(daily.get("time") or []):
        h = _num((daily.get("wave_height_max") or [None] * 9)[i])
        p = _num((daily.get("swell_wave_period_max") or [None] * 9)[i])
        try:
            name = datetime.strptime(day, "%Y-%m-%d").strftime("%a").upper()
        except ValueError:
            name = day
        r = surf_range(h, p)
        outlook.append({
            "name": "TODAY" if i == 0 else name,
            "height": h,
            "range": (f"{r[0]:.0f}-{r[1]:.0f}" if imperial else f"{r[0]:.1f}-{r[1]:.1f}") if r else "--",
            "period": f"{p:.0f}s" if p is not None else "",
            "dir": compass((daily.get("wave_direction_dominant") or [None] * 9)[i]),
        })
    report["outlook"] = outlook

    tides = client.tides()
    if tides:
        now = _local_now()
        upcoming = []
        for pred in tides["predictions"]:
            label, dt = _fmt_time(pred.get("t"))
            if dt is None or dt < now - timedelta(minutes=30):
                continue
            height = _num(pred.get("v"))
            upcoming.append({
                "kind": "HIGH" if pred.get("type") == "H" else "LOW",
                "time": label,
                "day": "" if dt.date() == now.date() else dt.strftime("%a").upper(),
                "height": f"{height:.1f} {len_unit}" if height is not None else "--",
            })
        report["tides"] = upcoming[:4]
        report["tide_station"] = tides["station"]["name"]
        report["source"] = f"{ATTRIBUTION} · {TIDE_ATTRIBUTION}"
    else:
        report["tides"] = []
    return report
