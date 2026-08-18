# Location label for Latitude/Longitude stations, which have no ZIP to look
# up. Nearest-city matching against a bundled worldwide table (GeoNames, see
# NOTICE.md) rather than a network reverse-geocoding call, for the same
# reason pws/data/zipcodes.py prefers its own offline table: the process
# resolving it often has no outbound network access.
from __future__ import annotations

import csv
from functools import lru_cache
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Optional

DATA_PATH = Path(__file__).with_name("world_cities.csv")
COUNTRIES_PATH = Path(__file__).with_name("countries.csv")

#: Beyond this, "nearest known city" stops being a meaningful label (open
#: ocean, polar regions, deep outback, etc.) and a raw coordinate is more
#: honest. The US ZIP/city grid is dense enough that 60mi never mattered
#: there, but plenty of populated, inhabited regions elsewhere (rural
#: Australia, the Canadian interior, ...) have no population-15k+ city
#: within 60mi despite being a perfectly reasonable place to run a station -
#: 150mi still excludes truly remote coordinates while covering those.
_MAX_MATCH_MILES = 150.0

#: Within this radius, prefer the most populous match over the literal
#: closest one - a big city's own districts are separate 15k+ population
#: entries, and are often geometrically closer to a given point than the
#: city's own centroid (e.g. "Paris 04" beating "Paris"). Wide enough to
#: reach a metro area's own centroid (Tokyo's is ~2.5mi from its geographic
#: middle), narrow enough that a genuinely distinct nearby town (e.g.
#: Levittown, PA, 8mi from Trenton) doesn't get swallowed by a bigger
#: neighbor.
_PREFER_POPULOUS_MILES = 5.0


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return r * c


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        with COUNTRIES_PATH.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("code") or "").strip().upper()
                name = (row.get("name") or "").strip()
                if code and name:
                    table[code] = name
    except OSError:
        pass
    return table


@lru_cache(maxsize=1)
def _city_table() -> tuple[tuple[str, str, str, float, float, int], ...]:
    rows: list[tuple[str, str, str, float, float, int]] = []
    try:
        with DATA_PATH.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                country = (row.get("country") or "").strip().upper()
                admin1 = (row.get("admin1") or "").strip().upper()
                try:
                    population = int(float(row.get("population") or 0))
                except (TypeError, ValueError):
                    population = 0
                rows.append((name, country, admin1, lat, lon, population))
    except OSError:
        pass
    return tuple(rows)


def nearest_city(lat: float, lon: float) -> Optional[dict]:
    """
    The best-matching bundled city for (lat, lon), or ``None`` if nothing is
    within ``_MAX_MATCH_MILES``.

    Among candidates within ``_PREFER_POPULOUS_MILES``, the most populous one
    wins over the literal closest one (see that constant's docstring);
    otherwise it's the single nearest match within ``_MAX_MATCH_MILES``.

    Returns ``{"city", "country", "admin1", "label"}`` - ``label`` is
    formatted "City, ST" for the US (matching the ZIP-lookup convention) and
    "City, Country" everywhere else.
    """
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return None

    nearest = None
    nearest_dist = _MAX_MATCH_MILES
    best_nearby = None
    best_nearby_pop = -1
    for name, country, admin1, city_lat, city_lon, population in _city_table():
        dist = _haversine_miles(lat, lon, city_lat, city_lon)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = (name, country, admin1)
        if dist <= _PREFER_POPULOUS_MILES and population > best_nearby_pop:
            best_nearby_pop = population
            best_nearby = (name, country, admin1)

    best = best_nearby or nearest
    if best is None:
        return None

    name, country, admin1 = best
    if country == "US" and admin1:
        label = f"{name}, {admin1}"
    else:
        region = _country_names().get(country, country)
        label = f"{name}, {region}" if region else name

    return {"city": name, "country": country, "admin1": admin1, "label": label}
