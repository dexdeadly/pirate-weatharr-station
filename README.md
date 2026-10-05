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

The channel cycles through eight pages (nine with a surf spot set), about 14
seconds each:

| Page | Contents |
|---|---|
| Current Conditions | Oversized temperature, condition icon, high/low labelled with the period they cover (see below), sun times, eight metric tiles |
| 12-Hour Trend | Temperature curve with precipitation-chance and cloud-cover series |
| 7-Day Forecast | Day cards with icons, highs/lows, a shared temperature range bar, plus precipitation, humidity, wind, gusts, cloud cover and UV per day |
| Live Radar | Animated NEXRAD/MRMS radar from NOAA over an OpenStreetMap base, with a dBZ legend and a source credit |
| Regional Conditions | Current temperatures at nearby cities, plotted on a map (see [Map cities](#map-cities)) |
| Forecast Highs | Today's high at those same cities (tomorrow's after 6 pm) |
| Extended Forecast | Narrative panels for today and tomorrow with an eight-value stat grid, feels-like, accumulation, visibility and moon phase |
| Surf Report | Only when a surf spot is set. Estimated surf height and rating, primary/secondary swell, wind, water temperature, next tides and a 5-day wave outlook. See [Surf report](#surf-report) |
| Almanac | Sunrise/sunset, dawn/dusk, a phase-accurate moon icon, UV, ozone, accumulations, fire index |

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
headlines you configure.

### Alert bar

Between the header and the page content, every page carries a colour-coded
alert bar:

| State | Colour | Shown for |
|---|---|---|
| NO ALERTS | Green | No active alerts for the location |
| WARNING | Amber | Watches, advisories and statements (or Minor/Moderate severity) |
| ALERT | Red | NWS Warnings and Emergencies (or Severe/Extreme severity) |
| NO DATA | Grey | The forecast couldn't be refreshed, so alert status is unknown |

The event name decides the tier before severity does, because NWS severities
are coarse (a Flood Watch is routinely "Severe" yet belongs in amber). With
several alerts active the bar rotates through them, most serious first, about
8 seconds each, and shows "1 of 3". Alert end times that aren't today include
the weekday ("until Fri 7:00 PM").

**Alert source.** For US locations PWS polls the National Weather Service's
alerts API directly every 60 seconds (free, no API key, no Pirate Weather
quota), so a new warning reaches the screen within about a minute instead of
waiting for the next forecast refresh — which with three stations could be 30
minutes. Outside the US, or if the NWS can't be reached for five minutes, the
bar falls back to the alerts carried in the Pirate Weather forecast.

### High and low

Pirate Weather's daily high covers 6 am–6 pm and its low the *following*
overnight (6 pm–6 am), so a plain "High / Low" could contradict the current
temperature at either end of the day. The Current Conditions pair follows the
station's local time and captions each value with its period:

| Local time | High | Low |
|---|---|---|
| 6 am – 6 pm | today | tonight |
| 6 pm – midnight | tomorrow | tonight |
| midnight – 6 am | today | overnight (lowest from now to 6 am, from the hourly forecast) |

After 6 pm the Extended Forecast also starts at Tomorrow rather than a "Today"
whose high has already passed.

---

## Install

1. Install **PWS - Pirate Weatharr Station** from Dispatcharr's plugin
   browser, or upload the release zip through **Plugins → Import Plugin**, or
   copy the folder manually into your Dispatcharr plugins directory as:

   ```
   /data/plugins/pirate_weatharr_station
   ```

   The folder name matters: Dispatcharr derives the plugin's permanent
   identity (settings storage, channel/logo linkage) from it, and a plugin
   browser update only replaces the install whose folder matches the
   registry name `pirate-weatharr-station` (as `pirate_weatharr_station`).
   The release zip is already structured that way; if copying manually, use
   exactly that folder name.
2. Restart Dispatcharr (or reload plugins from the UI).
3. Open **Plugins → PWS — Pirate Weather Station** and fill in the settings.
4. Press **Start**.

Channels are created in a group called **Weather**. A stream profile named
`proxy` is used if one exists, otherwise the first available profile.

### Upgrading from 1.4.x or earlier

Releases up to 1.4.2 installed into a folder named `pws`, which didn't match
the plugin browser's name for PWS, so **Update** always failed with "Plugin
'pws' already exists" and the only way forward was uninstall + reinstall.
From 1.5.0 the folder matches, so updates work in place from then on.

The first update to 1.5.0 installs next to the old entry instead of replacing
it (no uninstall needed):

1. Update (or install) PWS from the plugin browser, then **enable** the new
   entry when Dispatcharr asks.
2. Within about 20 seconds the new plugin adopts the old one: API key, every
   station's settings and the existing Weather channels are carried over (no
   duplicate channels), the old stations are stopped and the old entry is
   disabled. Stations that were running start again under the new plugin.
3. Delete the old, now-disabled **PWS** entry from the plugin list.

If you had already configured the new entry by hand before enabling it, the
old settings are left alone and nothing is copied.

### Capabilities

Dispatcharr's plugin manifest v2 gates what a plugin's own process may do,
similar to the permission prompts a mobile app requests at install. PWS
declares three:

| Capability | Why PWS needs it |
|---|---|
| `subprocess` | `_launch_process` spawns each station's renderer as `python -m pws.main` via `subprocess.Popen`. |
| `persistent_service` | That renderer runs detached (`setsid`) and outlives the Start action, tracked by PID/token across Start/Stop. |
| `network_listener` | `_is_port_available` binds a local socket to confirm a station's port is free before launching. |

PWS does not declare `outbound_network` — `plugin.py` itself makes no
`requests`/`urllib`/raw-socket calls; ZIP and coordinate resolution use the
bundled `pws/data/` lookup tables, not the network. It also does not declare
`filesystem_write` — the only writes `plugin.py` makes, its log and
start-lock file, stay inside the plugin's own `/data/plugins/pirate_weatharr_station/`
directory, which every plugin may always write to.

### Multiple stations

PWS runs up to **three stations**, each with its own location, renderer process
and channel. Station 1 is enabled by default; tick **Enable Station 2/3** and
give each a ZIP code — or a Latitude/Longitude, for locations outside the
US — to add more.

| Station | Port | Stream URL |
|---|---|---|
| 1 | 5960 | `http://127.0.0.1:5960/pws.ts` |
| 2 | 5961 | `http://127.0.0.1:5961/pws_2.ts` |
| 3 | 5962 | `http://127.0.0.1:5962/pws_3.ts` |

The API key, units, resolution, bitrate, refresh interval, radar source, music
volume and news feeds are shared by all stations. Only the location (ZIP or
Latitude/Longitude), display name and channel number are per station.

Each station's channel is named `{Location} - PWS` (e.g. `Levittown, PA -
PWS`) and uses the plugin's own icon as its channel logo. Both the name and
logo — along with the channel number, once set — stay in sync on every
subsequent Start, so changing a station's location or icon later updates the
existing channel rather than creating a new one.

Disabling a station and pressing **Start** again stops just that station and
leaves the others running. **Stop** halts all of them.

### Status and data freshness

The plugin's status line reports each running station's health, read from a
small status file its renderer rewrites every refresh, for example:

```
Houston, TX (ch 1001): forecast updated 7 min ago, 7,412/10,000 API calls left this month
```

or the current problem ("API key rejected", "monthly API quota exhausted",
DNS failures, …).

On screen, the right end of the alert bar shows when the forecast last
updated (`UPDATED 10:42 AM`). If refreshes keep failing, PWS keeps showing the
last good forecast rather than blanking the screen, and once that's older than
two refresh intervals (at least 15 minutes) the note turns amber:
`DATA DELAYED · 9:12 AM`.

### Changing settings, Restart and auto-start

Edit any setting and press **Start**: each running station compares what it was
launched with (location, units, radar, music, feeds, refresh interval, output,
surf spot, API key) and relaunches only if something changed; unchanged
stations keep running. **Restart** stops and relaunches every enabled station
regardless.

With **Auto-start Stations** on (the default), stations that were running come
back by themselves about 20 seconds after Dispatcharr restarts or the plugin is
updated. Pressing **Stop**, Reset to Defaults, or disabling the plugin turns
that off until the next Start, so a station you stopped stays stopped.

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

Shared settings, plus a repeated block per station (1–3). A few entries in
each block are just section-header text. Everything the API can tell us, we
ask the API instead of you — the timezone and elevation both arrive in the
same forecast response, so there are no fields for them.

| Setting | Required | Notes |
|---|---|---|
| Pirate Weather API Key | yes | Shared by all stations. Passed via the environment, never the command line |
| Enable Station 1–3 | — | Station 1 on by default; 2 and 3 optional |
| ZIP Code (per station) | yes, unless Lat/Long set | 5-digit US ZIP; resolved to coordinates and a city name offline, no network call needed |
| Latitude / Longitude (per station) | yes, unless ZIP set | Decimal degrees; for locations outside the US. Resolved to a nearby city name offline from a worldwide dataset |
| Location Name (per station) | no | Overrides the on-screen/channel name auto-resolved from the ZIP or Latitude/Longitude |
| Units | no | Imperial / Metric / SI / UK. Default Imperial |
| Data Refresh Interval | no | Minutes between Pirate Weather polls, per station. Default 10, 5–60 range. See [API quota](#api-quota) |
| Radar Source | no | NOAA (US only, default), RainViewer (worldwide), Auto, or Off |
| Background Music Volume | no | 0–100. 0 disables. Needs your own files in `assets/music` |
| Resolution | no | 4K, 1080p, 720p or 480p. Default 1080p |
| Video Bitrate | no | kbps. Default 3500 |
| Surf Spot Coordinates (per station) | no | `lat, lon` of a surf break, separate from the forecast location. Adds the Surf Report page; blank hides it |
| Surf Spot Name (per station) | no | On-screen name for the break, e.g. Huntington Pier |
| Channel Number (per station) | no | Auto-assigned from 1000 when blank |
| News Ticker Feeds | no | Comma-separated RSS/Atom URLs |
| Auto-start Stations | no | On by default. Relaunch stations that were running after Dispatcharr restarts or the plugin updates |

Frame rate is fixed at 30 fps.

---

## Map cities

Regional Conditions and Forecast Highs plot up to six cities around the
station, chosen offline from the bundled GeoNames table (places of 15,000+
people, worldwide):

- **Not the station's own area.** Nothing within 20 miles, no smaller suburb
  within 40 miles (a distinct city of 500,000+ that close still counts, e.g.
  Philadelphia for Levittown), and nothing with the station's own name. The
  map is still framed around the station; it just doesn't pin it.
- **Big and nearby wins.** Each city's population is weighted down with
  distance (halved at 75 miles), and cities in another country count for about
  a third, so the map stays regional.
- **Spread out.** Picks are made greedily with at least 50 miles between them
  (relaxed to 35, then 25, only if six don't fit), so they surround the
  station instead of stacking on one metro, and boroughs or neighbourhoods
  next to a bigger city are skipped.
- **Search 200 miles first,** widening to 360 only if too few cities fit, and
  falling back to the nearest places at any distance in very remote spots.

The cities' weather comes from [Open-Meteo](https://open-meteo.com/) — free,
no key, one request for all of them — every 30 minutes, so the map pages cost
nothing against your Pirate Weather quota. Only if Open-Meteo can't be reached
do they fall back to Pirate Weather (one call per city, on the slower regional
cadence below, paused when the monthly quota runs low).

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

## Surf report

Set **Surf Spot Coordinates** on a station (for example `33.6553, -118.0029`)
to add a Surf Report page. The spot is independent of the forecast location, so
an inland station can still report on its nearest break. All surf data comes
from free, keyless services and costs nothing against your Pirate Weather quota:

- **[Open-Meteo Marine](https://open-meteo.com/en/docs/marine-weather-api)** —
  significant wave height, primary and secondary swell (height, period,
  direction), sea-surface temperature and the 5-day outlook. Worldwide. The
  request snaps to the nearest ocean grid cell, so a pin on the sand still works.
- **[Open-Meteo Forecast](https://open-meteo.com/)** — wind speed, direction and
  gusts at the spot.
- **[NOAA CO-OPS](https://tidesandcurrents.noaa.gov/)** — high/low tide
  predictions from the nearest NOAA tide station within 60 miles. US coasts and
  territories only; elsewhere the tides panel says so.

Marine and wind data refresh every 30 minutes, tides every 6 hours. Open-Meteo's
free tier is for non-commercial use and allows 10,000 calls a day; each station
makes about 100.

The surf height is an **estimate**: it scales the open-ocean wave height by
swell period (long-period groundswell builds more on the way in), which is a
rule of thumb rather than a reef- or bathymetry-aware forecast. The FLAT / POOR
/ FAIR / GOOD / EPIC rating combines that size, the period and wind strength.
Wind direction isn't judged as onshore or offshore, since that depends on which
way the beach faces.

If the coordinates are inland or otherwise have no marine forecast, the page
says so instead of showing empty panels.

## Background music

A few example tracks ship with the plugin, so a fresh install has music out of
the box. Add your own `.mp3`, `.m4a`, `.aac`, `.flac`, `.ogg` or `.wav` files
(or delete the examples to use only yours) in:

```
pws/assets/music/
```

Each run picks one at random, loops it indefinitely and mixes it under the video
at the volume set in the plugin settings.

If the folder is empty, or the volume is 0, the stream carries a silent audio
track — the channel is valid and plays, there is simply nothing on the music
bed. Credits for the included tracks are in `NOTICE.md`.

Every startup logs what happened, so a silent channel is easy to diagnose from
the station's log (`pws_station<N>.log`):

```
[music] 12 track(s) from /data/plugins/pirate_weatharr_station/assets/music at 50% volume -> ...
[music] no audio files in /data/plugins/pirate_weatharr_station/assets/music - the channel will be silent...
[music] disabled (volume is 0)
```

Each station writes its own playlist file, so running several stations does not
have them clobbering one another.

## API quota

**This is the setting that matters most, so PWS manages it for you.**

Pirate Weather's free tier allows a fixed number of calls per month (10,000 at
time of writing). A naive port of the original NWS refresh loop would exhaust
that in days, so PWS budgets deliberately via the **Data Refresh Interval**
setting (default 10 minutes, the per-station baseline at one station):

- **Primary location** — one call every interval, roughly **4,300/month** at
  the 10-minute default. A single call returns current conditions, hourly,
  daily and alerts, so every page is fed from it.
- **Regional cities** — normally free: they come from Open-Meteo (see
  [Map cities](#map-cities)). Only as a fallback, if Open-Meteo is
  unreachable, are they fetched from Pirate Weather: six cities every 9x the
  interval (90 min at the default), up to **2,900/month** while it lasts.
- **Total** — about **4,300/month** at the default (at most ~7,200 during an
  Open-Meteo outage), leaving plenty of headroom.

**Running several stations does not multiply this.** Each station polls
independently, so three at the single-station cadence would cost ~21,600
calls/month — more than twice the free tier. PWS therefore scales the refresh
intervals by the number of enabled stations, holding the total flat regardless
of the interval you choose:

| Stations | Forecast refresh | Regional fallback refresh | Monthly calls |
|---|---|---|---|
| 1 | 10 min | 90 min | ~4,300 (≤ 7,200) |
| 2 | 20 min | 180 min | ~4,300 (≤ 7,200) |
| 3 | 30 min | 270 min | ~4,300 (≤ 7,200) |

The setting has a 5-minute floor - the lowest per-station baseline that still
keeps 3 stations under the free tier - and a 60-minute ceiling. Forecast data
changes slowly enough that even a 30-minute refresh is not noticeable on
screen; the clock and page cycling are local and keep updating regardless.

On top of the budget, the client:

- caches every response and serves from cache while fresh;
- reads the `X-RateLimit-Remaining` response header and **stops making regional
  calls once fewer than 750 remain**, so the primary feed keeps updating;
- backs off for an hour on HTTP 429 rather than hammering the gateway;
- serves the last good payload if a refresh fails, so the screen never blanks.

Radar and base map imagery (NOAA, RainViewer, OpenStreetMap), map-city weather
(Open-Meteo), alerts (NWS) and the surf page are all free and do not count
against your Pirate Weather quota.

---

## Running standalone

Useful for testing layout or diagnosing a start failure without Dispatcharr:

```bash
cd /data/plugins/pirate_weatharr_station
export PIRATE_WEATHER_API_KEY=your_key_here
python3 -m pws.main --zip 84101 --out file:out.ts --page-seconds 4
```

Other flags: `--units`, `--lat/--lon`, `--w/--h`, `--video-kbps`,
`--data-interval-sec`, `--regional-cities`, `--rss-url`, `--tz`.

---

## Layout

```
pirate_weatharr_station/   (install folder; the zip's top-level folder)
├── plugin.py               Dispatcharr plugin: settings, start/stop, channel wiring
├── plugin.json             Plugin manifest (generated from plugin.py)
├── logo.png                Plugin/channel icon (Dispatcharr plugin list + channel logo)
├── README.md
├── assets/
│   ├── fonts/              Inter (Regular → Black), OFL licensed
│   ├── icons/              Static PNG icons (unused fallback; icons are drawn)
│   └── logo.png            Station logo shown in the on-screen header
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
    ├── data/               ZIP, worldwide city and country lookup tables
    ├── surf.py             Surf data: Open-Meteo Marine/wind, NOAA tides
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
  panel redraw costs. The Almanac's moon icon is drawn the same way, but is
  phase-accurate rather than decorative: the lit fraction and waxing/waning
  side both match the real illumination for the day.
- **Icons are looked up, not guessed.** Pirate Weather returns a machine-readable
  `icon` key, so icon selection is a lookup rather than regex matching against
  English forecast prose.
- **Almanac replaces station observations.** Pirate Weather is a forecast model,
  not a station network, so there are no nearby METAR readings to list. The
  Almanac page surfaces the astronomical and air-quality fields that come free
  in the same payload instead.
- **Location lookups are offline, not live API calls.** ZIP codes and
  Latitude/Longitude both resolve to a place name from datasets bundled in
  `pws/data/` (GeoNames, see [NOTICE.md](NOTICE.md)) rather than a remote
  geocoding request. This matters specifically for channel naming, which
  happens inside Dispatcharr's own backend process — a process that often has
  no outbound network access, unlike the renderer subprocess.
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

Each station logs to its own file in the plugin folder — `pws_station1.log`,
`pws_station2.log`, `pws_station3.log`. A log is rotated once it passes 5 MB,
even while the station keeps running, keeping one previous file
(`pws_station1.log.1`).

> **Note on naming.** The plugin identifies itself as `PWS - Pirate Weather
> Station`. That string is deliberately kept clear of the upstream project's
> name: normalised, `weatharrstation` is a substring of
> `pirateweatharrstation`, which can make a plugin installer treat the two as
> the same plugin and offer to overwrite. Attribution lives in this README,
> `NOTICE.md` and the source headers — none of which are read as plugin
> identity — so credit and install safety do not conflict.
>
> Separately, the plugin's **install folder** must be named
> `pirate_weatharr_station` (see [Install](#install)) — that name is what
> Dispatcharr uses to derive the plugin's permanent settings/channel identity
> and to match plugin-browser updates, independent of the display name above.

| Symptom | Likely cause |
|---|---|
| "Failed to resolve api.pirateweather.net" | The container has no DNS or outbound access. Confirm the Dispatcharr host can reach `https://api.pirateweather.net` |
| "API key rejected" | Key not yet propagated, or the Forecast API subscription step was skipped |
| "monthly API quota exhausted" | Free tier used up; it resets monthly |
| "port 5960/5961/5962 is already in use" | A previous renderer did not exit; press Stop, then Start |
| "No stream profiles found" | Create a stream profile in Dispatcharr, ideally named `proxy` |
| Channel exists but no video | Check the station's log (`pws_station<N>.log`) for ffmpeg errors |
| Update fails with "Plugin 'pws' already exists" | You're on 1.4.x or earlier, installed in the old `pws` folder. Install 1.5.0 from the plugin browser (it goes in alongside), enable it, then delete the old entry — see [Upgrading from 1.4.x](#upgrading-from-14x-or-earlier) |
| Channel is named "Station N - PWS" instead of a location | Location Name, ZIP and Latitude/Longitude are all blank for that station |
| No background music | Volume is 0, or the music folder is empty (e.g. the examples were removed) — see below. The station's log (`pws_station<N>.log`) says exactly what was found |
| Radar echoes float on an empty background | The OpenStreetMap backdrop could not be fetched; the station's log (`pws_station<N>.log`) logs `[radar] base map fetch failed`. Check the host can reach `tile.openstreetmap.org` |
| Maps are empty | Open-Meteo is unreachable and the Pirate Weather fallback is paused for quota, or the first cities refresh hasn't run yet |

---

## Credits

- Weather data and logo artwork: [Pirate Weather](https://pirateweather.net/)
- Radar: [NOAA / National Weather Service](https://radar.weather.gov/) NEXRAD/MRMS
  base reflectivity (public domain), with [RainViewer](https://www.rainviewer.com/)
  as the worldwide alternative
- Base maps: [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- ZIP/city/country location lookups: [GeoNames](https://www.geonames.org/)
  (Creative Commons Attribution 4.0)
- Typeface: [Inter](https://rsms.me/inter/) by Rasmus Andersson (SIL Open Font License)
- Original project: [WeatharrStation](https://github.com/OkinawaBoss/WeatharrStation)
  by OkinawaBoss — PWS is derived from it and reuses its rendering pipeline.
  See [NOTICE.md](NOTICE.md).

Weather alerts are sourced from the US National Weather Service via Pirate
Weather and are available for US locations only.
