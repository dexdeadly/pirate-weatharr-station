"""
NOAA radar frames.

Pirate Weather is a forecast API and serves no radar imagery, so radar comes
from a separate source. This module pulls NEXRAD/MRMS base reflectivity
straight from the National Weather Service's public ArcGIS image service:

    https://mapservices.weather.noaa.gov/eventdriven/rest/services/
        radar/radar_base_reflectivity_time/ImageServer

The service is time-enabled with a rolling four-hour window updated every five
minutes, so an animation loop is just N ``exportImage`` requests at different
timestamps. It needs no API key and does not touch the Pirate Weather quota.

Coverage is the United States (CONUS, Alaska, Hawaii, the Caribbean and Guam).
Outside that footprint the service returns empty frames, which is why
``fetch_frames`` reports how much of each frame carried data - the caller can
then fall back to a global provider.

Attribution: imagery is public-domain US government work, credited on screen as
"NOAA / NWS" per the service's stated copyright.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone as dt_timezone
from io import BytesIO
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import requests
from PIL import Image

SERVICE_BASE = (
    "https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
    "radar/radar_base_reflectivity_time/ImageServer"
)
EXPORT_URL = f"{SERVICE_BASE}/exportImage"

#: Shown in the corner of the radar page.
ATTRIBUTION = "NOAA / NWS"

#: Guard against a rename mangling the host, as happened once before.
assert urlparse(SERVICE_BASE).hostname == "mapservices.weather.noaa.gov", (
    f"NOAA host looks corrupted: {SERVICE_BASE!r}"
)

_EARTH_CIRCUMFERENCE = 20037508.342789244


# ---------------------------------------------------------------------------
# Web Mercator helpers
# ---------------------------------------------------------------------------

def to_mercator(lat: float, lon: float) -> Tuple[float, float]:
    """EPSG:4326 -> EPSG:3857."""
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = float(lon) * _EARTH_CIRCUMFERENCE / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * _EARTH_CIRCUMFERENCE / math.pi
    return x, y


def bbox_for_bounds(lat_min: float, lon_min: float, lat_max: float,
                    lon_max: float) -> Tuple[float, float, float, float]:
    """Project a lat/lon box to a Web Mercator bbox."""
    x0, y0 = to_mercator(lat_min, lon_min)
    x1, y1 = to_mercator(lat_max, lon_max)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _export(bbox: Tuple[float, float, float, float], width: int, height: int,
            start_ms: int, end_ms: int, user_agent: str,
            timeout: int = 20) -> Optional[Image.Image]:
    """One ``exportImage`` call, returned as a transparent RGBA overlay."""
    params = {
        "bbox": ",".join(f"{v:.2f}" for v in bbox),
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": f"{int(width)},{int(height)}",
        "format": "png32",
        "transparent": "true",
        "interpolation": "RSP_BilinearInterpolation",
        # A short window rather than an instant: the mosaic is assembled from
        # scans with slightly different valid times.
        "time": f"{int(start_ms)},{int(end_ms)}",
        "f": "image",
    }
    try:
        resp = requests.get(
            EXPORT_URL, params=params,
            headers={"User-Agent": user_agent, "Accept": "image/png"},
            timeout=timeout,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "image" not in ctype:
        # The service answers errors with JSON and HTTP 200.
        return None
    try:
        return Image.open(BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


def _coverage(img: Image.Image) -> float:
    """Fraction of pixels carrying radar returns (non-transparent)."""
    try:
        alpha = img.getchannel("A")
        histogram = alpha.histogram()
        total = sum(histogram) or 1
        opaque = sum(histogram[16:])
        return opaque / total
    except Exception:
        return 0.0


def fit_aspect(bbox: Tuple[float, float, float, float], width: int,
               height: int) -> Tuple[float, float, float, float]:
    """
    Expand a bbox about its centre so its aspect matches the output image.

    ArcGIS honours the requested pixel size regardless of the bbox shape, so a
    mismatch silently stretches the radar. Always widen rather than crop, so the
    requested area stays fully visible.
    """
    x0, y0, x1, y1 = bbox
    bw, bh = (x1 - x0), (y1 - y0)
    if bw <= 0 or bh <= 0 or width <= 0 or height <= 0:
        return bbox
    target = float(width) / float(height)
    current = bw / bh
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if current < target:
        bw = bh * target
    else:
        bh = bw / target
    return (cx - bw / 2.0, cy - bh / 2.0, cx + bw / 2.0, cy + bh / 2.0)


def fetch_frames(
    lat_min: float,
    lon_min: float,
    lat_max: float,
    lon_max: float,
    width: int,
    height: int,
    user_agent: str,
    *,
    frames: int = 6,
    step_minutes: int = 10,
    tz=None,
) -> List[dict]:
    """
    Fetch an animation loop, oldest frame first.

    Each entry is ``{"image", "label", "timestamp", "coverage"}``. Frames with
    no returns anywhere are dropped, so an empty list means either a genuinely
    clear sky or that the location sits outside NOAA's coverage; the caller
    decides which by whether *any* frame came back.
    """
    bbox = fit_aspect(bbox_for_bounds(lat_min, lon_min, lat_max, lon_max),
                      width, height)
    frames = max(1, min(12, int(frames)))
    step_ms = max(1, int(step_minutes)) * 60_000
    now_ms = int(time.time() * 1000)

    out: List[dict] = []
    for i in range(frames - 1, -1, -1):
        end_ms = now_ms - i * step_ms
        start_ms = end_ms - step_ms
        img = _export(bbox, width, height, start_ms, end_ms, user_agent)
        if img is None:
            continue
        stamp = datetime.fromtimestamp(end_ms / 1000.0, tz=dt_timezone.utc)
        if tz is not None:
            try:
                stamp = stamp.astimezone(tz)
            except Exception:
                pass
        out.append({
            "image": img,
            "label": stamp.strftime("%I:%M %p").lstrip("0"),
            "timestamp": end_ms // 1000,
            "coverage": _coverage(img),
        })
    return out


def service_available(user_agent: str, timeout: int = 10) -> bool:
    """Cheap reachability probe used for source selection and diagnostics."""
    try:
        resp = requests.get(
            SERVICE_BASE, params={"f": "json"},
            headers={"User-Agent": user_agent}, timeout=timeout,
        )
        return resp.status_code == 200 and "radar" in resp.text[:4000].lower()
    except requests.RequestException:
        return False
