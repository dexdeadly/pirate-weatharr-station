<img width="1084" height="320" alt="pws_lockup_plate_2x" src="https://github.com/user-attachments/assets/193686c1-981a-481c-a407-40d09b48f98b" />
# PWS — Pirate Weather Station

A self-hosted, TV-style weather channel for [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr).
PWS pulls forecast data from the [Pirate Weather API](https://pirateweather.net/),
renders it as a looping broadcast, and publishes the result as a channel.

Based on [OkinawaBoss/WeatharrStation](https://github.com/OkinawaBoss/WeatharrStation),
rebuilt around a single-call weather provider, square-cornered broadcast
graphics and animated icons. See [NOTICE.md](NOTICE.md) for what is reused.

---

## Pages

The channel cycles through eight pages, about 14 seconds each:

| Page | Contents |
|---|---|
| Current Conditions | Oversized temperature, condition icon, high/low, sun times, eight metric tiles |
| 12-Hour Trend | Temperature curve with precipitation-chance and cloud-cover series |
| 7-Day Forecast | Day cards with icons, highs/lows, a shared temperature range bar, plus precipitation, humidity, wind, gusts, cloud cover and UV per day |
| Live Radar | Animated NEXRAD/MRMS radar from NOAA over an OpenStreetMap base, with a dBZ legend and a source credit |
| Regional Conditions | Current temperatures at nearby cities, plotted on a map |
| Forecast Highs | Tomorrow's highs at those same cities |
| Extended Forecast | Narrative panels for today and tomorrow with an eight-value stat grid, feels-like, accumulation, visibility and moon phase |
| Almanac | Sunrise/sunset, dawn/dusk, moon phase, UV, ozone, accumulations, fire index |

### Header

The header is a fixed four-column band, present on every page. Column 1 leads
with the station logo (`assets/logo.png`); swap that file to rebrand, and the
header picks up the new artwork automatically at any resolution. If the file is
missing, the lockup falls back to a plain accent bar.


| 1 | 2 | 3 | 4 |
|---|---|---|---|
| Station identity and location | Current page title | Current temperature | Local time and date |

The four columns are equal quarters of the band. Column 1 sits flush to the
left page margin so the logotype lines up with the content cards below;
columns 2, 3 and 4 centre their content, which keeps the spacing even no matter
how long the page title happens to be.

Columns 3 and 4 update independently of the rest of the header, so the
temperature and clock stay live without repainting the whole band. Column
geometry lives in `pws/layout.py` — edit the weights there and all four columns
plus their dividers move together.

A ticker runs along the bottom: active weather alerts first, then any RSS
headlines you configure. Severe alerts also raise a coloured banner under the
header on every page.

---

## Install

1. Copy the `PWS` folder into your Dispatcharr plugins directory:

   ```
   /data/plugins/PWS
   ```

2. Restart Dispatcharr (or reload plugins from the UI).
3. Open **Plugins → PWS — Pirate Weather Station** and fill in the settings.
4. Press **Start**.

Channels are created in a group called **Weather**. A stream profile named
`proxy` is used if one exists, otherwise the first available profile.

### Multiple stations

PWS runs up to **three stations**, each with its own location, renderer process
and channel. Station 1 is enabled by default; tick **Enable Station 2/3** and
give each a ZIP code to add more.

| Station | Port | Stream URL |
|---|---|---|
| 1 | 5960 | `http://127.0.0.1:5960/pws.ts` |
| 2 | 5961 | `http://127.0.0.1:5961/pws_2.ts` |
| 3 | 5962 | `http://127.0.0.1:5962/pws_3.ts` |

The API key, units, resolution, bitrate, radar source, music volume and news
feeds are shared by all stations. Only the ZIP, display name and channel number
are per station.

Disabling a station and pressing **Start** again stops just that station and
leaves the others running. **Stop** halts all of them.

### Requirements

- Dispatcharr with plugin support
- `ffmpeg` on the host (already required by Dispatcharr)
- Python packages: `pillow`, `numpy`, `requests` — all already present in a
  standard Dispatcharr install

---

## Getting an API key

1. Sign up at <https://pirateweather.net/>.
2. Log in and **subscribe to the Forecast API** — this step is easy to miss, and
   without it every request returns HTTP 401.
3. Copy your key into the plugin settings.

A new key can take up to 20 minutes to propagate. If PWS reports a rejected key
right after signup, wait and try again.

---

## Settings

Nine entries, one of which is just help text. Everything the API can tell us, we
ask the API instead of you — the timezone, city name and elevation all arrive in
the same forecast response, so there are no fields for them.

| Setting | Required | Notes |
|---|---|---|
| Pirate Weather API Key | yes | Shared by all stations. Passed via the environment, never the command line |
| Enable Station 1–3 | — | Station 1 on by default; 2 and 3 optional |
| ZIP Code (per station) | yes | 5-digit US ZIP; resolved to coordinates and a city name |
| Location Name (per station) | no | Overrides the on-screen name resolved from the ZIP |
| Units | no | Imperial / Metric / SI / UK. Default Imperial |
| Radar Source | no | NOAA (US only, default), RainViewer (worldwide), Auto, or Off |
| Background Music Volume | no | 0–100. 0 disables. Needs your own files in `assets/music` |
| Resolution | no | 4K, 1080p, 720p or 480p. Default 1080p |
| Video Bitrate | no | kbps. Default 3500 |
| Channel Number (per station) | no | Auto-assigned from 1000 when blank |
| News Ticker Feeds | no | Comma-separated RSS/Atom URLs |

Frame rate is fixed at 30 fps.

---

## Radar

Pirate Weather is a forecast API and serves no radar imagery, so radar comes
from a separate source and costs nothing against your Pirate Weather quota.

- **NOAA / NWS** (default) — NEXRAD/MRMS base reflectivity from the National
  Weather Service's public ArcGIS image service. No key required. Covers the
  United States, Alaska, Hawaii, the Caribbean and Guam only.
- **RainViewer** — worldwide coverage; use this outside the US.
- **Auto** — tries NOAA first and falls back to RainViewer when NOAA returns no
  data, which is what happens outside its footprint.
- **Off** — hides the radar page entirely.

The credit in the bottom-right corner names whichever source actually supplied
the frames, so it stays accurate when Auto falls back.

NOAA returns bare transparent reflectivity with no geography in it, so PWS
fetches an OpenStreetMap backdrop for the same area and composites the two. The
backdrop is requested once and cached, and the radar overlay is requested for
the backdrop's own tile-snapped bounds so the two line up exactly.

## Background music

Music is off unless you supply it. Drop `.mp3`, `.m4a`, `.aac`, `.flac`,
`.ogg` or `.wav` files into:

```
PWS/assets/music/
```

They are shuffled, looped indefinitely and mixed under the video at the volume
set in the plugin settings.

**No audio ships with the plugin.** Bundling music of unknown licensing would
not be redistributable, so an untouched install streams a silent audio track —
the channel is valid and plays, there is simply nothing on the music bed. If you
have another weather-channel plugin installed, copying its `assets/music`
contents across works.

Every startup logs what happened, so a silent channel is easy to diagnose from
`pws.log`:

```
[music] 12 track(s) from /data/plugins/PWS/assets/music at 50% volume -> ...
[music] no audio files in /data/plugins/PWS/assets/music - the channel will be silent...
[music] disabled (volume is 0)
```

Each station writes its own playlist file, so running several stations does not
have them clobbering one another.

## API quota

**This is the setting that matters most, so PWS manages it for you.**

Pirate Weather's free tier allows a fixed number of calls per month (10,000 at
time of writing). A naive port of the original NWS refresh loop would exhaust
that in days, so PWS budgets deliberately:

- **Primary location** — one call every 10 minutes, roughly **4,300/month**.
  A single call returns current conditions, hourly, daily and alerts, so every
  page is fed from it.
- **Regional cities** — six cities refreshed every 90 minutes, roughly
  **2,900/month**. These drive only the two map pages.
- **Total** — about **7,200/month**, leaving headroom.

**Running several stations does not multiply this.** Each station polls
independently, so three at the single-station cadence would cost ~21,600
calls/month — more than twice the free tier. PWS therefore scales the refresh
intervals by the number of enabled stations, holding the total flat:

| Stations | Forecast refresh | Regional refresh | Monthly calls |
|---|---|---|---|
| 1 | 10 min | 90 min | ~7,200 |
| 2 | 20 min | 180 min | ~7,200 |
| 3 | 30 min | 270 min | ~7,200 |

Forecast data changes slowly enough that a 30-minute refresh is not noticeable
on screen; the clock and page cycling are local and keep updating regardless.

On top of the budget, the client:

- caches every response and serves from cache while fresh;
- reads the `X-RateLimit-Remaining` response header and **stops making regional
  calls once fewer than 750 remain**, so the primary feed keeps updating;
- backs off for an hour on HTTP 429 rather than hammering the gateway;
- serves the last good payload if a refresh fails, so the screen never blanks.

Radar and base map imagery come from RainViewer and OpenStreetMap, which are
free and do not count against your Pirate Weather quota.

---

## Running standalone

Useful for testing layout or diagnosing a start failure without Dispatcharr:

```bash
cd /data/plugins/PWS
export PIRATE_WEATHER_API_KEY=your_key_here
python3 -m pws.main --zip 84101 --out file:out.ts --page-seconds 4
```

Other flags: `--units`, `--lat/--lon`, `--w/--h`, `--video-kbps`,
`--data-interval-sec`, `--regional-cities`, `--rss-url`, `--tz`.

---

## Layout

```
PWS/
├── plugin.py               Dispatcharr plugin: settings, start/stop, channel wiring
├── plugin.json             Plugin manifest (generated from plugin.py)
├── README.md
├── assets/
│   ├── fonts/              Inter (Regular → Black), OFL licensed
│   ├── icons/              Static PNG icons (unused fallback; icons are drawn)
│   └── logo.png            Station logo shown in the header
└── pws/
    ├── main.py             Renderer entry point
    ├── config.py           CLI configuration
    ├── pirate.py           Pirate Weather client: caching, quota governance
    ├── normalize.py        API schema → render contract, unit handling
    ├── theme.py            Design system: palette, fonts, cards, gradients
    ├── icons_anim.py       Animated weather icons, drawn procedurally
    ├── layout.py           Header column geometry
    ├── layers/             One module per on-screen element
    ├── pages via main.py   Page composition and cycling
    ├── core/               Compositor, scheduler, layer base, datastore
    ├── output/             ffmpeg streaming
    ├── data/               ZIP and city lookup tables
    └── map_tiles.py        OSM base maps + RainViewer radar
```

### Design notes

- **Every daily element is surfaced.** A single forecast call already carries
  humidity, dew point, wind, gusts, cloud cover, UV, pressure, visibility,
  apparent temperatures, accumulations, sun times and moon phase for all seven
  days, so the forecast pages show them rather than just highs and lows. None of
  this costs extra quota.
- **One provider call per refresh.** Pirate Weather is Dark Sky-compatible, so
  current conditions, hourly, daily and alerts all arrive together. An NWS-based
  equivalent needs four or more requests, including a separate gridpoint call
  just for cloud cover.
- **Icons are animated and drawn, not loaded.** The sun's rays rotate, clouds
  drift, rain and snow fall, lightning flashes and fog banks slide. They are
  drawn in code (`icons_anim.py`) rather than loaded from bitmaps, so every loop
  closes seamlessly and icons stay crisp at any size. Layers cache their static
  background and repaint only the icon rectangles each frame, which keeps a
  frame of animation at well under a millisecond instead of the ~500 ms a full
  panel redraw costs.
- **Icons are looked up, not guessed.** Pirate Weather returns a machine-readable
  `icon` key, so icon selection is a lookup rather than regex matching against
  English forecast prose.
- **Almanac replaces station observations.** Pirate Weather is a forecast model,
  not a station network, so there are no nearby METAR readings to list. The
  Almanac page surfaces the astronomical and air-quality fields that come free
  in the same payload instead.
- **Square-cornered, hard-edged graphics.** Rounded corners, blurred drop
  shadows and translucent top highlights read as generic soft-UI, so the
  station uses flat panels with crisp hairline borders instead. The switches
  live at the top of `theme.py` (`SQUARE_CORNERS`, `SOFT_SHADOWS`,
  `BACKGROUND_GLOW`, `TOP_HIGHLIGHT`) and every radius in the codebase is
  funnelled through `theme.radius_of()`, so the rounded treatment can be
  restored by flipping one flag.
- **Fonts are resolved absolutely.** Relative font paths silently fall back to a
  bitmap font whenever the working directory differs, so all font loading goes
  through `theme.font()`, which resolves an absolute path and caches the result.

---

## Troubleshooting

Logs are written to `PWS/pws.log` inside the plugin folder.

> **Note on naming.** The plugin identifies itself as `PWS - Pirate Weather
> Station`. That string is deliberately kept clear of the upstream project's
> name: normalised, `weatharrstation` is a substring of
> `pirateweatharrstation`, which can make a plugin installer treat the two as
> the same plugin and offer to overwrite. Attribution lives in this README,
> `NOTICE.md` and the source headers — none of which are read as plugin
> identity — so credit and install safety do not conflict.

| Symptom | Likely cause |
|---|---|
| "Failed to resolve api.pirateweather.net" | The container has no DNS or outbound access. Confirm the Dispatcharr host can reach `https://api.pirateweather.net` |
| "API key rejected" | Key not yet propagated, or the Forecast API subscription step was skipped |
| "monthly API quota exhausted" | Free tier used up; it resets monthly |
| "port 5960/5961/5962 is already in use" | A previous renderer did not exit; press Stop, then Start |
| "No stream profiles found" | Create a stream profile in Dispatcharr, ideally named `proxy` |
| Channel exists but no video | Check `pws.log` for ffmpeg errors |
| No background music | Nothing ships with the plugin — see below. `pws.log` says exactly what was found |
| Radar echoes float on an empty background | The OpenStreetMap backdrop could not be fetched; `pws.log` logs `[radar] base map fetch failed`. Check the host can reach `tile.openstreetmap.org` |
| Maps are empty | Regional lookups are paused for quota, or the cities refresh has not run yet |

---

## Credits

- Weather data and logo artwork: [Pirate Weather](https://pirateweather.net/)
- Radar: [NOAA / National Weather Service](https://radar.weather.gov/) NEXRAD/MRMS
  base reflectivity (public domain), with [RainViewer](https://www.rainviewer.com/)
  as the worldwide alternative
- Base maps: [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- Typeface: [Inter](https://rsms.me/inter/) by Rasmus Andersson (SIL Open Font License)
- Original project: [WeatharrStation](https://github.com/OkinawaBoss/WeatharrStation)
  by OkinawaBoss — PWS is derived from it and reuses its rendering pipeline.
  See [NOTICE.md](NOTICE.md).

Weather alerts are sourced from the US National Weather Service via Pirate
Weather and are available for US locations only.
