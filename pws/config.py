"""Command-line configuration for the renderer process."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/config.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_WIDTH = 1920
BASE_HEIGHT = 1080

#: Every page, in the default rotation order. Radar is skipped when the radar
#: source is off, Surf Report when no surf spot is set.
PAGE_NAMES = ("current", "hourly", "daily", "radar", "regional",
              "forecast_map", "forecast_text", "surf", "almanac")


def parse_pages(raw: str | None) -> list[str]:
    """'daily, current radar' -> known page names in that order, de-duplicated.
    Empty or nothing recognisable means every page in the default order."""
    seen: list[str] = []
    for token in (raw or "").replace(",", " ").split():
        name = token.strip().lower().replace("-", "_")
        if name in PAGE_NAMES and name not in seen:
            seen.append(name)
    return seen or list(PAGE_NAMES)


@dataclass
class Location:
    """One place a channel shows. A channel can take turns between several."""
    name: str
    zip: str | None = None
    lat: float | None = None
    lon: float | None = None
    surf_lat: float | None = None
    surf_lon: float | None = None
    surf_name: str = ""

    @property
    def has_surf(self) -> bool:
        return self.surf_lat is not None and self.surf_lon is not None


def parse_locations(raw: str | None) -> list[Location]:
    """--locations-json: a list of {name, zip, lat, lon, surf_lat, surf_lon, surf_name}."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        raise SystemExit("--locations-json is not valid JSON")
    out: list[Location] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        def num(key):
            try:
                return float(item[key]) if item.get(key) not in (None, "") else None
            except (TypeError, ValueError):
                return None
        loc = Location(
            name=str(item.get("name") or "").strip(),
            zip=(str(item.get("zip") or "").strip() or None),
            lat=num("lat"), lon=num("lon"),
            surf_lat=num("surf_lat"), surf_lon=num("surf_lon"),
            surf_name=str(item.get("surf_name") or "").strip(),
        )
        if loc.zip or (loc.lat is not None and loc.lon is not None):
            out.append(loc)
    return out


@dataclass
class Config:
    # Provider
    api_key: str
    units: str

    # Location
    zip: str | None
    lat: float | None
    lon: float | None
    location_name: str

    # Output surface
    width: int
    height: int
    output_fps: int
    video_kbps: int
    out_url: str

    # Data refresh
    data_interval_sec: int
    regional_interval_sec: int
    regional_cities: int
    radar_source: str

    # UI
    ticker_speed_px_per_sec: int
    page_duration_sec: int
    pages: list[str]
    clock_24h: bool
    timezone: str | None
    music_dir: str | None
    music_fifo: str | None
    music_volume: float
    user_agent: str

    # Surf report (optional; blank lat/lon hides the page)
    surf_lat: float | None = None
    surf_lon: float | None = None
    surf_name: str = ""

    # Every location this channel shows, in order (one for a normal station).
    locations: list[Location] = field(default_factory=list)

    # News ticker
    rss_urls: list[str] = field(default_factory=list)
    rss_refresh_sec: int = 300
    rss_max_items: int = 3


def _default_music_dir() -> str | None:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents[:4]):
        candidate = parent / "assets" / "music"
        if candidate.is_dir():
            return str(candidate)
    return None


def parse_args(argv: list[str] | None = None) -> Config:
    p = argparse.ArgumentParser("pws")

    provider = p.add_argument_group("Pirate Weather")
    # The key may also arrive via environment so it never appears in `ps` output.
    provider.add_argument("--api-key", type=str, default=None,
                          help="Pirate Weather API key (or set PIRATE_WEATHER_API_KEY)")
    provider.add_argument("--units", type=str, default="us",
                          choices=("us", "si", "ca", "uk"),
                          help="Unit system; 'us' is Imperial (default)")

    loc = p.add_argument_group("Location")
    loc.add_argument("--zip", type=str, default=None, help="5-digit US ZIP code")
    loc.add_argument("--lat", type=float, default=None)
    loc.add_argument("--lon", type=float, default=None)
    loc.add_argument("--location-name", type=str, default="PWS")

    out = p.add_argument_group("Output")
    out.add_argument("--w", "--width", dest="width", type=int, default=BASE_WIDTH)
    out.add_argument("--h", "--height", dest="height", type=int, default=BASE_HEIGHT)
    out.add_argument("--output-fps", type=int, default=30)
    out.add_argument("--video-kbps", type=int, default=3500)
    out.add_argument("--out", dest="out_url", type=str,
                     default="udp://127.0.0.1:5000?pkt_size=1316")

    data = p.add_argument_group("Data & UI")
    # 600s keeps a single station near ~4,300 calls/month, inside the free tier.
    data.add_argument("--data-interval-sec", type=int, default=600,
                      help="Primary forecast refresh interval (quota-sensitive)")
    data.add_argument("--regional-interval-sec", type=int, default=5400,
                      help="Refresh interval for regional city lookups")
    data.add_argument("--regional-cities", type=int, default=6,
                      help="How many nearby cities to plot on the map pages")
    data.add_argument("--radar-source", type=str, default="noaa",
                      choices=("noaa", "rainviewer", "auto", "off"),
                      help="Radar imagery source; 'off' removes the radar page")
    data.add_argument("--ticker-speed", dest="ticker_speed_px_per_sec",
                      type=int, default=120)
    data.add_argument("--page-seconds", dest="page_duration_sec", type=int, default=14)
    data.add_argument("--pages", type=str, default=",".join(PAGE_NAMES),
                      help="Pages to show, in order: " + ", ".join(PAGE_NAMES))
    data.add_argument("--clock", choices=("auto", "12", "24"), default="auto",
                      help="12- or 24-hour times; auto = 12h for 'us' units, else 24h")
    data.add_argument("--tz", "--timezone", dest="timezone", type=str, default=None,
                      help="IANA timezone; auto-detected from the API when omitted")
    data.add_argument("--music-dir", type=str, default=None)
    data.add_argument("--music-fifo", type=str, default=None)
    data.add_argument("--music-volume", type=float, default=0.5,
                      help="Background music gain, 0.0 silences it")
    # Identifies the app (and where to reach its maintainer) to the free
    # services it uses - OpenStreetMap and the NWS both require this.
    data.add_argument("--user-agent", type=str,
                      default="PWS-PirateWeatherStation (+https://github.com/dexdeadly/pirate-weatharr-station)")

    surf = p.add_argument_group("Surf report")
    surf.add_argument("--surf-lat", type=float, default=None,
                      help="Surf spot latitude; with --surf-lon adds the Surf Report page")
    surf.add_argument("--surf-lon", type=float, default=None)
    surf.add_argument("--surf-name", type=str, default="")

    p.add_argument("--locations-json", type=str, default=None,
                   help="JSON list of locations shown in turn on this channel "
                        "(overrides --zip/--lat/--lon/--location-name/--surf-*)")

    rss = p.add_argument_group("News / RSS")
    rss.add_argument("--rss-url", dest="rss_urls", action="append", default=[])
    rss.add_argument("--rss-refresh-sec", type=int, default=300)
    rss.add_argument("--rss-max-items", type=int, default=3)

    args = p.parse_args(argv)

    api_key = (args.api_key or os.environ.get("PIRATE_WEATHER_API_KEY") or "").strip()

    surf_lat = args.surf_lat if args.surf_lon is not None else None
    surf_lon = args.surf_lon if args.surf_lat is not None else None
    locations = parse_locations(args.locations_json) or [Location(
        name=args.location_name, zip=args.zip, lat=args.lat, lon=args.lon,
        surf_lat=surf_lat, surf_lon=surf_lon, surf_name=(args.surf_name or "").strip(),
    )]

    return Config(
        locations=locations,
        api_key=api_key,
        units=args.units,
        zip=args.zip,
        lat=args.lat,
        lon=args.lon,
        location_name=args.location_name,
        width=args.width,
        height=args.height,
        output_fps=max(1, min(60, args.output_fps)),
        video_kbps=max(500, min(20000, args.video_kbps)),
        out_url=args.out_url,
        data_interval_sec=max(120, args.data_interval_sec),
        regional_interval_sec=max(600, args.regional_interval_sec),
        regional_cities=max(0, min(12, args.regional_cities)),
        radar_source=args.radar_source,
        ticker_speed_px_per_sec=max(10, args.ticker_speed_px_per_sec),
        page_duration_sec=max(4, args.page_duration_sec),
        pages=parse_pages(args.pages),
        clock_24h=(args.clock == "24") or (args.clock == "auto" and args.units != "us"),
        timezone=args.timezone,
        music_dir=args.music_dir or _default_music_dir(),
        music_fifo=args.music_fifo,
        music_volume=max(0.0, min(1.0, args.music_volume)),
        user_agent=args.user_agent,
        surf_lat=args.surf_lat if args.surf_lon is not None else None,
        surf_lon=args.surf_lon if args.surf_lat is not None else None,
        surf_name=(args.surf_name or "").strip(),
        rss_urls=args.rss_urls or [],
        rss_refresh_sec=max(60, min(3600, args.rss_refresh_sec)),
        rss_max_items=max(1, min(50, args.rss_max_items)),
    )
