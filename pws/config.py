"""Command-line configuration for the renderer process."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/config.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_WIDTH = 1920
BASE_HEIGHT = 1080


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
    timezone: str | None
    music_dir: str | None
    music_fifo: str | None
    music_volume: float
    user_agent: str

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
    data.add_argument("--tz", "--timezone", dest="timezone", type=str, default=None,
                      help="IANA timezone; auto-detected from the API when omitted")
    data.add_argument("--music-dir", type=str, default=None)
    data.add_argument("--music-fifo", type=str, default=None)
    data.add_argument("--music-volume", type=float, default=0.5,
                      help="Background music gain, 0.0 silences it")
    data.add_argument("--user-agent", type=str, default="PWS/1.0")

    rss = p.add_argument_group("News / RSS")
    rss.add_argument("--rss-url", dest="rss_urls", action="append", default=[])
    rss.add_argument("--rss-refresh-sec", type=int, default=300)
    rss.add_argument("--rss-max-items", type=int, default=3)

    args = p.parse_args(argv)

    api_key = (args.api_key or os.environ.get("PIRATE_WEATHER_API_KEY") or "").strip()

    return Config(
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
        timezone=args.timezone,
        music_dir=args.music_dir or _default_music_dir(),
        music_fifo=args.music_fifo,
        music_volume=max(0.0, min(1.0, args.music_volume)),
        user_agent=args.user_agent,
        rss_urls=args.rss_urls or [],
        rss_refresh_sec=max(60, min(3600, args.rss_refresh_sec)),
        rss_max_items=max(1, min(50, args.rss_max_items)),
    )
