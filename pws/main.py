"""
Renderer entry point.

Pulls forecast data from Pirate Weather, normalizes it, builds the page layers,
and streams composited RGBA frames to ffmpeg.

Run standalone for testing:

    python -m pws.main --api-key KEY --zip 84101 --out file:out.ts
"""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/main.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

import os
import random
import sys
import tempfile
import threading
import time
import math
import xml.etree.ElementTree as ET

from PIL import Image
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pws import icons_anim, layout, map_tiles, noaa_radar, normalize, theme
from pws.config import BASE_HEIGHT, BASE_WIDTH, Config, parse_args
from pws.core.compositor import Compositor
from pws.core.datastore import DataStore
from pws.core.layer import Layer
from pws.core.scheduler import Scheduler
from pws.data.major_cities import major_cities_near
from pws.data.zipcodes import resolve_zip
from pws.layers.almanac import AlmanacLayer
from pws.layers.chrome import ChromeLayer
from pws.layers.clock import ClockLayer
from pws.layers.header_current import HeaderCurrentLayer
from pws.layers.current import CurrentLayer
from pws.layers.daily import DailyLayer
from pws.layers.forecast_text import ForecastTextLayer
from pws.layers.hourly_graph import HourlyGraphLayer
from pws.layers.maps import ForecastMapLayer, RegionalLayer
from pws.layers.radar import RadarLayer
from pws.layers.ticker import TickerLayer
from pws.output.stream_ffmpeg import FFMPEGStreamer
from pws.pirate import PirateWeatherClient, PirateWeatherError
from pws.utils import compute_bounds, local_tzinfo, set_timezone


# ---------------------------------------------------------------------------
# RSS (stdlib only)
# ---------------------------------------------------------------------------

class _RssTitleCache:
    """Fetches and caches headline titles from RSS/Atom feeds."""

    _UA = "PWS-RSS/1.0"

    def __init__(self, urls: list[str], refresh_sec: int = 300, max_items: int = 3):
        self.urls = urls or []
        self.refresh_sec = max(60, int(refresh_sec or 300))
        self.max_items = max(1, int(max_items or 3))
        self._last = 0.0
        self._titles: list[str] = []

    def _get(self, url: str) -> bytes | None:
        try:
            req = Request(url, headers={"User-Agent": self._UA})
            with urlopen(req, timeout=10) as resp:
                return resp.read()
        except (URLError, HTTPError, TimeoutError, ValueError, OSError):
            return None

    def _titles_from(self, payload: bytes) -> list[str]:
        out: list[str] = []
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            return out
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if title:
                out.append(title)
                if len(out) >= self.max_items:
                    return out
        if not out:
            for entry in root.findall(".//{*}entry"):
                title = (entry.findtext("{*}title") or "").strip()
                if title:
                    out.append(title)
                    if len(out) >= self.max_items:
                        return out
        return out

    def titles(self) -> list[str]:
        if not self.urls:
            return []
        now = time.time()
        if now - self._last < self.refresh_sec:
            return list(self._titles)
        collected: list[str] = []
        for url in self.urls:
            payload = self._get(url)
            if payload:
                collected.extend(self._titles_from(payload))
        seen: set[str] = set()
        unique: list[str] = []
        for title in collected:
            key = title.lower()
            if key not in seen:
                seen.add(key)
                unique.append(title)
        self._titles = unique
        self._last = now
        return list(unique)


# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------

def _make_datastore(cfg: Config, client: PirateWeatherClient, units,
                    render_w: int, render_h: int, scale: float) -> DataStore:
    """
    Background refresh thread.

    One Pirate Weather call feeds every page for the primary location. Regional
    city lookups are billed separately and run on a much slower cadence, guarded
    by the client's monthly-quota check.
    """
    lat, lon = client.lat, client.lon
    rss = _RssTitleCache(cfg.rss_urls, cfg.rss_refresh_sec, cfg.rss_max_items)
    radar_state: dict[str, float] = {"last_ts": 0.0}
    regional_state: dict[str, object] = {"at": 0.0, "current": [], "forecast": []}

    def _compose_map(points: list[dict]):
        if not points:
            return None, None
        coords = [
            (p.get("lat"), p.get("lon")) for p in points
            if p.get("lat") is not None and p.get("lon") is not None
        ]
        bounds = compute_bounds(coords, lat, lon, pad_degrees=0.35,
                                min_span=2.0, max_span=None)
        width = max(200, render_w - int(round(192 * scale)))
        height = max(200, render_h - int(round(472 * scale)))
        try:
            view = map_tiles.compose_base_map(
                bounds[0], bounds[1], bounds[2], bounds[3],
                width, height, cfg.user_agent,
            )
        except Exception:
            view = None
        if view is not None:
            return view.image.copy(), view.bounds
        return None, bounds

    def _refresh_regional(now: float) -> None:
        """Slow-cadence secondary lookups for the two map pages."""
        if cfg.regional_cities <= 0:
            return
        last = float(regional_state.get("at") or 0.0)
        if last and now - last < cfg.regional_interval_sec:
            return
        if not client.budget_ok_for_secondary():
            return

        targets = major_cities_near(
            lat, lon, max_distance=360.0, max_results=cfg.regional_cities
        )
        current_points: list[dict] = []
        forecast_points: list[dict] = []
        for target in targets:
            payload = client.point_forecast(target["lat"], target["lon"])
            if not payload:
                continue
            point = normalize.build_city_point(
                target["name"], target["lat"], target["lon"], payload, units
            )
            if point:
                current_points.append(point)
            fpoint = normalize.build_city_forecast_point(
                target["name"], target["lat"], target["lon"], payload, units
            )
            if fpoint:
                forecast_points.append(fpoint)

        if current_points or forecast_points:
            regional_state["current"] = current_points
            regional_state["forecast"] = forecast_points
            regional_state["at"] = now

    radar_state.update({"source": None, "frames": [], "at": 0.0, "served": 0,
                        "base": None, "base_key": None})

    def _radar_base_map(bounds, width: int, height: int):
        """
        OpenStreetMap backdrop for the radar page, fetched once and cached.

        NOAA's image service returns bare transparent reflectivity with no
        geography under it, so without this the echoes float on an empty
        background. Returns (image, actual_bounds) - the composer snaps to tile
        edges, so its bounds are what the overlay must be requested for.
        """
        key = (tuple(round(v, 4) for v in bounds), width, height)
        if radar_state.get("base_key") == key and radar_state.get("base") is not None:
            return radar_state["base"], radar_state["base_bounds"]
        try:
            view = map_tiles.compose_base_map(
                bounds[0], bounds[1], bounds[2], bounds[3],
                width, height, cfg.user_agent,
            )
        except Exception as exc:
            print(f"[radar] base map fetch failed: {exc!r}", flush=True)
            return None, bounds
        if view is None:
            return None, bounds
        base = view.image.convert("RGBA")
        # Dim and cool the map so reflectivity colours stay dominant.
        base = Image.alpha_composite(base, Image.new("RGBA", base.size, (10, 15, 32, 140)))
        radar_state["base"] = base
        radar_state["base_key"] = key
        radar_state["base_bounds"] = view.bounds
        return base, view.bounds

    def _radar_bounds() -> tuple[float, float, float, float]:
        """Lat/lon box around the home location for the radar view."""
        span_lat = 3.0
        span_lon = span_lat / max(0.2, math.cos(math.radians(lat)))
        return (lat - span_lat / 2, lon - span_lon / 2,
                lat + span_lat / 2, lon + span_lon / 2)

    def _refresh_radar(now: float, width: int, height: int) -> None:
        """
        Refresh the radar loop from the configured source.

        NOAA covers the United States only, so when it yields nothing the
        fetcher falls back to RainViewer rather than leaving the page blank.
        """
        if cfg.radar_source == "off":
            return
        if radar_state["at"] and now - radar_state["at"] < 300:
            return

        b = _radar_bounds()
        got: list[dict] = []
        source = None

        if cfg.radar_source in ("noaa", "auto"):
            # Fetch the backdrop first: its tile-snapped bounds are what the
            # radar overlay must be requested for, or the two will not line up.
            base, aligned = _radar_base_map(b, width, height)
            try:
                got = noaa_radar.fetch_frames(
                    aligned[0], aligned[1], aligned[2], aligned[3],
                    width, height, cfg.user_agent,
                    frames=6, step_minutes=10, tz=local_tzinfo(),
                )
                if got and base is not None:
                    for f in got:
                        overlay = f["image"]
                        if overlay.size != base.size:
                            overlay = overlay.resize(base.size, Image.LANCZOS)
                        f["image"] = Image.alpha_composite(base, overlay)
            except Exception as exc:
                print(f"[radar] NOAA fetch failed: {exc!r}", flush=True)
                got = []
            if got:
                source = noaa_radar.ATTRIBUTION
                if not any(f.get("coverage", 0) > 0.0005 for f in got):
                    # Frames returned but entirely empty: almost certainly
                    # outside NOAA's footprint.
                    if cfg.radar_source == "auto":
                        print("[radar] NOAA returned no echoes; trying RainViewer",
                              flush=True)
                        got = []
                        source = None

        if not got and cfg.radar_source in ("rainviewer", "auto", "noaa"):
            try:
                map_tiles.ensure_radar_frames(
                    announce=False, center_lat=lat, center_lon=lon,
                    width=width, height=height, user_agent=cfg.user_agent,
                    span_degrees=3.0, max_frames=6,
                )
                cached = map_tiles.get_cached_radar_frames() or []
                got = [
                    {"image": f["image"], "label": f.get("label") or "",
                     "timestamp": f.get("timestamp") or 0, "coverage": 1.0}
                    for f in cached if f.get("image") is not None
                ]
            except Exception as exc:
                print(f"[radar] RainViewer fetch failed: {exc!r}", flush=True)
                got = []
            if got:
                source = "RainViewer"

        if got:
            if source != radar_state.get("source"):
                print(f"[radar] source: {source}", flush=True)
            radar_state["frames"] = got
            radar_state["source"] = source
            radar_state["at"] = now
            radar_state["served"] = 0

    def _radar_getter() -> list:
        """Hand each newly fetched frame to the layer exactly once."""
        frames = radar_state.get("frames") or []
        served = int(radar_state.get("served") or 0)
        if served >= len(frames):
            return []
        radar_state["served"] = len(frames)
        return [(f["image"].copy(), f.get("label") or "") for f in frames[served:]]

    def _ticker(alerts: list[dict]) -> tuple[str, str]:
        """Return (text, category-label) for the ticker."""
        headlines = rss.titles()
        alert_text = normalize.alerts_ticker_text(alerts)
        if alerts and headlines:
            joined = "  •  ".join(headlines)
            return (f"{alert_text}  •  {joined}", "ALERTS")
        if alerts:
            return (alert_text, "ALERTS")
        if headlines:
            return ("  •  ".join(headlines), "NEWS")
        return (alert_text, "WEATHER")

    def fetch_all() -> dict:
        data: dict[str, object] = {}
        now = time.time()

        try:
            payload = client.forecast()
            data["error"] = None
        except PirateWeatherError as exc:
            data["error"] = str(exc)
            data["ticker_text"] = f"Pirate Weather unavailable — {exc}"
            data["ticker_label"] = "STATUS"
            return data

        alerts = normalize.build_alerts(payload)
        data["alerts"] = alerts
        data["current"] = normalize.build_current(payload, units, cfg.location_name)
        data["daily_days"] = normalize.build_daily_days(payload, units)
        data["forecast_periods"] = normalize.build_forecast_periods(payload, units)
        data["hourly_points"] = normalize.build_hourly_points(payload, units, limit=12)
        data["almanac_rows"] = normalize.build_almanac(payload, units)

        text, label = _ticker(alerts)
        data["ticker_text"] = text
        data["ticker_label"] = label

        _refresh_regional(now)
        regional_points = list(regional_state.get("current") or [])
        forecast_points = list(regional_state.get("forecast") or [])

        # Always include the home location so the maps are never empty.
        current = data["current"] or {}
        if isinstance(current, dict):
            home_current = {
                "name": cfg.location_name.split(",")[0].strip() or "Home",
                "lat": lat, "lon": lon,
                "temp": current.get("temp_display", "--"),
                "temp_f": current.get("temp_f"),
                "condition": current.get("summary", ""),
                "icon": current.get("icon", "clear-day"),
                "is_day": current.get("is_day", True),
            }
            if not any(p.get("name") == home_current["name"] for p in regional_points):
                regional_points.insert(0, home_current)
            days = data.get("daily_days") or []
            if isinstance(days, list) and days:
                home_forecast = {
                    "name": home_current["name"],
                    "lat": lat, "lon": lon,
                    "forecast_temp": normalize._deg(days[0].get("high"), units),
                    "temp_f": days[0].get("high_f"),
                    "forecast_short": days[0].get("short", ""),
                    "icon": days[0].get("icon", "clear-day"),
                    "is_day": True,
                }
                if not any(p.get("name") == home_forecast["name"] for p in forecast_points):
                    forecast_points.insert(0, home_forecast)

        data["regional_points"] = regional_points
        data["forecast_points"] = forecast_points

        regional_image, regional_bounds = _compose_map(regional_points)
        forecast_image, forecast_bounds = _compose_map(forecast_points)
        data["regional_map_image"] = regional_image
        data["regional_map_bounds"] = regional_bounds
        data["forecast_map_image"] = forecast_image
        data["forecast_map_bounds"] = forecast_bounds

        radar_w = max(200, render_w - int(round(160 * scale)))
        radar_h = max(200, render_h - int(round(432 * scale)))
        _refresh_radar(now, radar_w, radar_h)
        data["radar_new_frames"] = _radar_getter
        data["radar_source"] = radar_state.get("source") or ""
        data["quota"] = client.quota_summary()
        return data

    store = DataStore(fetcher=fetch_all, interval_sec=max(30, cfg.data_interval_sec // 4))
    store.start()
    return store


# ---------------------------------------------------------------------------
# Page cycling
# ---------------------------------------------------------------------------

class PageCycler:
    """Toggles layer-group visibility on a fixed cadence."""

    def __init__(self, pages: list[dict], interval_sec: float):
        self.pages = pages
        self.interval = max(1.0, float(interval_sec or 1.0))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._index = 0

    def activate(self, index: int) -> None:
        if not self.pages:
            return
        self._index = index % len(self.pages)
        for i, page in enumerate(self.pages):
            visible = i == self._index
            for layer in page.get("layers", []):
                if isinstance(layer, Layer):
                    layer.set_visible(visible)

    def start(self) -> None:
        if not self.pages or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="page-cycler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.activate(self._index + 1)


# ---------------------------------------------------------------------------
# Layer / page construction
# ---------------------------------------------------------------------------

def _build_layers(cfg: Config, store: DataStore, render_w: int, render_h: int,
                  scale: float) -> tuple[list[Layer], PageCycler]:
    layers: list[Layer] = []
    pages: list[dict] = []

    def s(value: float, minimum: int = 0) -> int:
        return max(minimum, int(round(value * scale)))

    def read(key: str, default=None):
        value = store.read().get(key)
        return default if value is None else value

    def content_bounds(top: int, bottom_extra: int = 24) -> tuple[int, int, int, int]:
        x = s(48)
        y = s(top)
        w = max(s(320, 1), render_w - s(96))
        ticker_h = s(64, 1)
        h = max(s(160, 1), render_h - (y + ticker_h + s(22) + s(bottom_extra)))
        return (x, y, w, h)

    # --- persistent header columns 3 & 4 + ticker -----------------------
    columns = layout.header_columns(render_w, s)
    band_top = s(layout.LABEL_Y) - s(6)
    band_h = s(layout.HEADER_H) - band_top - s(8)

    col_temp_x, col_temp_w = columns[2]
    header_current = HeaderCurrentLayer(
        x=col_temp_x, y=band_top, w=col_temp_w, h=band_h,
        get_data=lambda: read("current", {}) or {},
        min_interval=5.0, scale=scale,
    )
    header_current.z = 200
    layers.append(header_current)

    col_time_x, col_time_w = columns[3]
    clock = ClockLayer(
        x=col_time_x, y=band_top, w=col_time_w, h=band_h,
        min_interval=1.0, scale=scale,
    )
    clock.z = 200
    layers.append(clock)

    ticker_h = s(64, 1)
    ticker = TickerLayer(
        x=s(48), y=render_h - ticker_h - s(22),
        w=render_w - s(96), h=ticker_h,
        min_interval=1 / 30.0,
        px_per_sec=max(1, int(round(cfg.ticker_speed_px_per_sec * scale))),
        get_text=lambda: str(read("ticker_text", "") or ""),
        get_label=lambda: str(read("ticker_label", "WEATHER") or "WEATHER"),
        get_accent=lambda: theme.ALERT if read("alerts", []) else theme.ACCENT,
        scale=scale,
    )
    ticker.z = 200
    layers.append(ticker)

    def add_page(name: str, title: str,
                 builder: Callable[[tuple[int, int, int, int]], list[Layer]],
                 *, top: int) -> None:
        bounds = content_bounds(top)
        chrome = ChromeLayer(
            width=render_w, height=render_h,
            location_name=cfg.location_name,
            page_title=title,
            get_alerts=lambda: read("alerts", []) or [],
            scale=scale,
        )
        chrome.z = 0
        page_layers: list[Layer] = [chrome]
        for layer in builder(bounds):
            layer.z = max(getattr(layer, "z", 50), 50)
            page_layers.append(layer)
        for layer in page_layers:
            layer.set_visible(False)
        pages.append({"name": name, "layers": page_layers})
        layers.extend(page_layers)

    add_page("current", "Current Conditions", lambda b: [
        CurrentLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                     get_data=lambda: read("current", {}) or {},
                     min_interval=5.0, scale=scale)
    ], top=262)

    add_page("hourly", "12-Hour Trend", lambda b: [
        HourlyGraphLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                         get_points=lambda: read("hourly_points", []) or [],
                         min_interval=15.0, scale=scale)
    ], top=262)

    add_page("daily", "7-Day Forecast", lambda b: [
        DailyLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                   get_days=lambda: read("daily_days", []) or [],
                   min_interval=30.0, scale=scale)
    ], top=262)

    if cfg.radar_source != "off":
        add_page("radar", "Live Radar", lambda b: [
            RadarLayer(x=b[0], y=b[1], w=b[2], h=b[3], min_interval=0.25,
                       get_new_frames=lambda: (
                           lambda fn: fn() if callable(fn) else []
                       )(store.read().get("radar_new_frames")),
                       get_source=lambda: str(read("radar_source", "") or ""),
                       frame_hold=3, scale=scale)
        ], top=262)

    add_page("regional", "Regional Conditions", lambda b: [
        RegionalLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                      get_points=lambda: read("regional_points", []) or [],
                      get_map=lambda: (lambda im: im.copy() if im is not None else None)(
                          store.read().get("regional_map_image")),
                      get_bounds=lambda: store.read().get("regional_map_bounds"),
                      min_interval=20.0, scale=scale)
    ], top=262)

    add_page("forecast_map", "Forecast Highs", lambda b: [
        ForecastMapLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                         get_points=lambda: read("forecast_points", []) or [],
                         get_map=lambda: (lambda im: im.copy() if im is not None else None)(
                             store.read().get("forecast_map_image")),
                         get_bounds=lambda: store.read().get("forecast_map_bounds"),
                         min_interval=20.0, scale=scale)
    ], top=262)

    add_page("forecast_text", "Extended Forecast", lambda b: [
        ForecastTextLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                          get_periods=lambda: read("forecast_periods", []) or [],
                          min_interval=30.0, scale=scale)
    ], top=262)

    add_page("almanac", "Almanac", lambda b: [
        AlmanacLayer(x=b[0], y=b[1], w=b[2], h=b[3],
                     get_rows=lambda: read("almanac_rows", []) or [],
                     min_interval=20.0, scale=scale)
    ], top=262)

    cycler = PageCycler(pages, cfg.page_duration_sec)
    if pages:
        cycler.activate(0)
    return layers, cycler


# ---------------------------------------------------------------------------
# Shutdown watcher
# ---------------------------------------------------------------------------

def _build_disable_checker() -> Optional[Callable[[], bool]]:
    """Stop the renderer if the Dispatcharr plugin is disabled from the UI."""
    plugin_key = os.environ.get("PWS_PLUGIN_KEY")
    if not plugin_key:
        return None
    interval = float(os.environ.get("PWS_DISABLE_CHECK_INTERVAL", "5"))
    state = {"last": 0.0, "ready": False}

    def should_stop() -> bool:
        now = time.time()
        if now - state["last"] < interval:
            return False
        state["last"] = now
        try:
            import django
            if not state["ready"]:
                os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
                django.setup()
                state["ready"] = True
            from apps.plugins.models import PluginConfig
            config = PluginConfig.objects.filter(key=plugin_key).first()
            if not config or not config.enabled:
                return True
            return False
        except Exception:
            return False

    return should_stop


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _build_music_playlist(cfg: Config) -> str | None:
    """
    Write an ffmpeg concat playlist for the background music bed.

    Returns ``None`` when music is disabled or no audio files are present, in
    which case the stream carries a silent audio track. Every outcome is logged
    so a silent channel can be diagnosed from pws.log alone.
    """
    if cfg.music_volume <= 0.0:
        print("[music] disabled (volume is 0)", flush=True)
        return None
    if not cfg.music_dir:
        print("[music] no music directory could be located", flush=True)
        return None

    directory = Path(cfg.music_dir).expanduser()
    if not directory.is_dir():
        print(f"[music] directory not found: {directory}", flush=True)
        return None

    tracks = [
        p for p in sorted(directory.iterdir())
        if p.is_file() and p.suffix.lower() in
        {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga"}
    ]
    if not tracks:
        print(
            f"[music] no audio files in {directory} - the channel will be "
            f"silent. Drop .mp3/.m4a/.aac/.flac/.ogg/.wav files there and "
            f"restart to enable background music.",
            flush=True,
        )
        return None

    # Shuffle so a looping channel does not always open with the same track.
    random.shuffle(tracks)

    # One playlist per station: sibling stations share a plugin key, so a single
    # shared path had them truncating each other's file at startup.
    key = os.environ.get("PWS_PLUGIN_KEY", "pws")
    station = os.environ.get("PWS_STATION_INDEX", "1")
    playlist = Path(tempfile.gettempdir()) / f"{key}_station{station}_music.txt"
    with playlist.open("w", encoding="utf-8") as fh:
        for track in tracks:
            fh.write("file '%s'\n" % track.as_posix().replace("'", "'\\''"))

    print(
        f"[music] {len(tracks)} track(s) from {directory} "
        f"at {int(cfg.music_volume * 100)}% volume -> {playlist}",
        flush=True,
    )
    return str(playlist)


def main(argv: Optional[list[str]] = None) -> int:
    cfg = parse_args(argv)

    if not cfg.api_key:
        print("[pws] FATAL: no API key. Pass --api-key or set "
              "PIRATE_WEATHER_API_KEY.", flush=True)
        return 2

    # Resolve ZIP -> coordinates when explicit lat/lon were not supplied.
    if (cfg.lat is None or cfg.lon is None) and cfg.zip:
        lookup = resolve_zip(cfg.zip)
        if lookup:
            cfg.lat = cfg.lat if cfg.lat is not None else lookup.get("lat")
            cfg.lon = cfg.lon if cfg.lon is not None else lookup.get("lon")
            if cfg.location_name == "PWS":
                city = (lookup.get("city") or "").strip()
                state = (lookup.get("state") or "").strip()
                resolved = f"{city}, {state}".strip(", ")
                if resolved:
                    cfg.location_name = resolved
    if cfg.lat is None or cfg.lon is None:
        print("[pws] FATAL: could not resolve a location. Provide a "
              "valid --zip or explicit --lat/--lon.", flush=True)
        return 2

    units = normalize.units_for(cfg.units)

    try:
        client = PirateWeatherClient(
            api_key=cfg.api_key,
            lat=cfg.lat,
            lon=cfg.lon,
            units=cfg.units,
            cache_ttl=cfg.data_interval_sec,
            secondary_ttl=cfg.regional_interval_sec,
            user_agent=cfg.user_agent,
        )
    except PirateWeatherError as exc:
        print(f"[pws] FATAL: {exc}", flush=True)
        return 2

    # Timezone: prefer the explicit setting, else let the API tell us.
    tz_name = cfg.timezone
    if not tz_name:
        try:
            tz_name = client.timezone_name()
        except PirateWeatherError as exc:
            print(f"[pws] WARNING: initial fetch failed: {exc}", flush=True)
            tz_name = None
    set_timezone(tz_name, cfg.lat, cfg.lon)
    print(f"[pws] location={cfg.location_name} "
          f"({cfg.lat:.3f},{cfg.lon:.3f}) tz={tz_name or 'system'} "
          f"units={cfg.units}", flush=True)

    output_w = int(cfg.width) if cfg.width > 0 else BASE_WIDTH
    output_h = int(cfg.height) if cfg.height > 0 else BASE_HEIGHT
    scale = min(output_w / BASE_WIDTH, output_h / BASE_HEIGHT)

    streamer = FFMPEGStreamer(
        width=output_w, height=output_h, fps=cfg.output_fps,
        out_url=cfg.out_url, out_width=output_w, out_height=output_h,
        music_fifo=None, music_playlist=_build_music_playlist(cfg),
        music_volume=cfg.music_volume,
        video_encoder="auto", encoder_preset="veryfast",
        vb_kbps=cfg.video_kbps, ab_kbps=128,
        gop_seconds=1.0, srt_latency_ms=120, udp_pkt_size=1316,
        pat_period=0.5, pcr_period_ms=40, print_cmd=True,
    )
    streamer.start()

    # Build the icon animation loops before the first frame so playback never
    # stalls mid-stream.
    icons_anim.prewarm(
        icons_anim.SUPPORTED,
        [int(round(v * scale)) for v in (62, 84, 96, 190)],
    )

    store = _make_datastore(cfg, client, units, output_w, output_h, scale)
    layers, cycler = _build_layers(cfg, store, output_w, output_h, scale)
    compositor = Compositor(w=output_w, h=output_h)
    scheduler = Scheduler(layers=layers, cfr_hz=cfg.output_fps)
    cycler.start()

    def on_present(image) -> None:
        try:
            streamer.send(image.tobytes())
        except Exception as exc:
            print(f"[stream] write failed: {exc!r}", flush=True)

    try:
        scheduler.run_forever(compositor=compositor, on_present=on_present,
                              should_stop=_build_disable_checker())
    except KeyboardInterrupt:
        pass
    finally:
        for shutdown in (store.stop, cycler.stop, streamer.stop):
            try:
                shutdown()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
