# Reused essentially unchanged from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/data/zipcodes.py)
# See NOTICE.md for provenance and licensing status.
#
# ZIP -> city/state/lat/lon resolves from a bundled offline table first (see
# us_zipcodes.csv, from GeoNames - NOTICE.md), so it works even when the
# process resolving it has no outbound network access, as is often the case
# for a Dispatcharr plugin's own backend. The remote API is only a fallback
# for the handful of codes not in the snapshot.
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests

_TABLE_PATH = Path(__file__).with_name("us_zipcodes.csv")


def _normalize_zip(zip_code: str | int | None) -> str | None:
    if zip_code is None:
        return None
    if isinstance(zip_code, int):
        return f"{zip_code:05d}"
    digits = [ch for ch in str(zip_code) if ch.isdigit()]
    if len(digits) < 5:
        return None
    return "".join(digits[:5])


@lru_cache(maxsize=1)
def _local_table() -> dict[str, dict]:
    table: dict[str, dict] = {}
    try:
        with _TABLE_PATH.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("zip") or "").strip()
                if not code or code in table:
                    continue
                try:
                    lat = float(row["lat"])
                    lon = float(row["lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                table[code] = {
                    "zip": code,
                    "lat": lat,
                    "lon": lon,
                    "city": (row.get("city") or "").strip(),
                    "state": (row.get("state") or "").strip(),
                }
    except OSError:
        pass
    return table


@lru_cache(maxsize=1024)
def _lookup_remote(code: str) -> Optional[dict]:
    url = f"https://api.zippopotam.us/us/{code}"
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None

    places = data.get("places") or []
    if not places:
        return None

    first = places[0]
    try:
        lat = float(first.get("latitude"))
        lon = float(first.get("longitude"))
    except (TypeError, ValueError):
        return None

    return {
        "zip": code,
        "lat": lat,
        "lon": lon,
        "city": (first.get("place name") or "").strip(),
        "state": (first.get("state abbreviation") or first.get("state") or "").strip(),
    }


def resolve_zip(zip_code: str | int) -> Optional[dict]:
    code = _normalize_zip(zip_code)
    if not code:
        return None
    hit = _local_table().get(code)
    if hit:
        return dict(hit)
    result = _lookup_remote(code)
    if result:
        return dict(result)
    return None
