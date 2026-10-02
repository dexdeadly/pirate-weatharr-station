"""
Pick the nearby cities plotted on the Regional Conditions and Forecast Highs
maps.

Replaces the upstream WeatharrStation picker, which took the *nearest* cities
over 150k people from a US-only table. That table was geocoded by name alone
(every "Columbus" carried Columbus, OH's coordinates; "Corona" had Corona, CA's
population at a point in Queens), and "nearest first" clustered picks: a
Levittown, PA station got five New York-area places stacked on one corner of
the map, where their labels collided and hid each other.

Now:

* one catalog: the bundled GeoNames table (world_cities.csv, places of 15k+
  with real coordinates and state/region), for the US and everywhere else;
* the station's own area is never picked - nothing within HOME_EXCLUSION_MILES,
  no smaller suburb within SUBURB_MILES, nothing sharing the station's name -
  since the map is about its surroundings;
* candidates are ranked by population weighted down steeply with distance, and
  cities in another country count for less, so the map stays regional (search
  REGIONAL_MILES first, widening to MAX_DISTANCE_MILES only if too few fit);
* picks are chosen greedily with a minimum spacing between them, which spreads
  them around the station and drops boroughs/neighbourhoods that sit on top of
  a bigger city (Corona, Harlem, Astoria next to New York City).
"""
from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt
from typing import List, Optional

from pws.data.world_cities import _city_table

#: Places this close to the station are its own area and are never plotted.
HOME_EXCLUSION_MILES = 20.0
#: Out to here, only distinct major cities (MAJOR_CITY_POP+) are plotted;
#: smaller places are the station's own suburbs (Cypress for Houston).
SUBURB_MILES = 40.0
MAJOR_CITY_POP = 500_000
#: Search radii: regional first, widened only if too few cities fit.
REGIONAL_MILES = 200.0
MAX_DISTANCE_MILES = 360.0
#: Distance (miles) at which a city's weight has halved; see _score.
DISTANCE_FALLOFF_MILES = 75.0
#: Weight multiplier for cities outside the station's country.
FOREIGN_WEIGHT = 0.35
#: Minimum gap between picks, relaxed step by step only if too few cities fit.
SPACING_STEPS_MILES = (50.0, 35.0, 25.0)


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi, dlambda = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def _score(population: int, dist: float) -> float:
    """Population, halved at DISTANCE_FALLOFF_MILES and falling off beyond."""
    return population / (1.0 + (dist / DISTANCE_FALLOFF_MILES) ** 2)


def _home_key(name: Optional[str]) -> str:
    return (name or "").split(",")[0].strip().lower()


def _station_country(lat: float, lon: float) -> str:
    best, best_d = "", float("inf")
    for _name, country, _admin1, c_lat, c_lon, _pop in _city_table():
        d = _haversine_miles(lat, lon, c_lat, c_lon)
        if d < best_d:
            best, best_d = country, d
    return best


def major_cities_near(
    lat: float,
    lon: float,
    *,
    max_distance: float = MAX_DISTANCE_MILES,
    max_results: int = 6,
    home_name: Optional[str] = None,
    home_exclusion: float = HOME_EXCLUSION_MILES,
) -> List[dict]:
    """
    Up to ``max_results`` well-spread cities around (lat, lon), most
    significant first, excluding the station's own area.

    Returns ``[{"name", "lat", "lon", "population", "distance"}, ...]``.
    """
    if max_results <= 0:
        return []
    home = _home_key(home_name)
    country = _station_country(lat, lon)

    within: list[tuple[float, float, str, float, float, int]] = []
    for name, c_country, _admin1, c_lat, c_lon, population in _city_table():
        dist = _haversine_miles(lat, lon, c_lat, c_lon)
        if dist > max_distance or dist <= home_exclusion:
            continue
        if dist <= SUBURB_MILES and population < MAJOR_CITY_POP:
            continue
        if home and name.strip().lower() == home:
            continue
        score = _score(population, dist) * (1.0 if c_country == country else FOREIGN_WEIGHT)
        within.append((score, dist, name, c_lat, c_lon, population))
    within.sort(key=lambda c: c[0], reverse=True)

    picked: list[tuple[float, float, str, float, float, int]] = []
    for radius in (min(REGIONAL_MILES, max_distance), max_distance):
        candidates = [c for c in within if c[1] <= radius]
        for spacing in SPACING_STEPS_MILES:
            for cand in candidates:
                if len(picked) >= max_results:
                    break
                if cand in picked:
                    continue
                if all(_haversine_miles(cand[3], cand[4], p[3], p[4]) >= spacing
                       for p in picked):
                    picked.append(cand)
            if len(picked) >= max_results:
                break
        if len(picked) >= max_results:
            break

    if not picked:
        # Nothing of 15k+ within range (remote interior, small islands): use
        # the closest places at any distance so the map isn't empty.
        nearest = sorted(
            (_haversine_miles(lat, lon, c_lat, c_lon), name, c_lat, c_lon, population)
            for name, _c, _a, c_lat, c_lon, population in _city_table()
        )
        picked = [(0.0, d, n, la, lo, pop) for d, n, la, lo, pop in nearest
                  if d > home_exclusion and n.strip().lower() != home][:max_results]

    return [
        {"name": name, "lat": c_lat, "lon": c_lon, "population": population,
         "distance": round(dist, 1)}
        for _score_, dist, name, c_lat, c_lon, population in picked
    ]
