# NOTICE

PWS (Pirate Weather Station) is derived from **WeatharrStation** by
**OkinawaBoss**:

> https://github.com/OkinawaBoss/WeatharrStation

That project established the architecture this one is built on: the layered
compositor and scheduler, the Dispatcharr plugin lifecycle (start/stop, channel
and stream provisioning, PID supervision), the ffmpeg output pipeline and the
map/radar tile handling. PWS would not exist without it.

## What is reused verbatim

These files are taken from WeatharrStation essentially unchanged, apart from
import renaming (`weatherstream` → `pws`) and formatting:

| File | Purpose |
|---|---|
| `pws/core/layer.py` | Layer base class and dirty-rect contract |
| `pws/core/compositor.py` | Frame compositor |
| `pws/core/scheduler.py` | Per-layer tick scheduling and CFR presentation |
| `pws/core/datastore.py` | Background refresh thread |
| `pws/map_tiles.py` | OpenStreetMap base maps and RainViewer radar frames |
| `pws/utils.py` | Timezone, geometry and formatting helpers |
| `pws/data/zipcodes.py` | ZIP code → coordinate lookup |
| `pws/data/major_cities.py` | Nearby-city lookup table |

## What is partially derived

`pws/main.py`, `pws/config.py` and several layers under `pws/layers/` follow the
upstream structure but have been substantially rewritten (typically 3–37% textual
similarity) for the new data provider and visual design.

`pws/output/stream_ffmpeg.py` is upstream's ffmpeg process management and
streaming code with a music-gain filter added.

## What is new

`pws/pirate.py`, `pws/normalize.py`, `pws/theme.py`, `pws/layout.py`,
`pws/noaa_radar.py`, `pws/icons_anim.py`, `pws/layers/anim_icons.py`,
`pws/layers/almanac.py`,
`pws/layers/header_current.py` and `pws/layers/maps.py` were written for this
project.

Measured at the time of writing: roughly 1,400 of ~5,450 lines of shipped Python
(about 26%) originate from WeatharrStation.

## Licensing status

**WeatharrStation does not currently include a LICENSE file.** Under default
copyright that means no explicit grant to copy, modify or redistribute the work.
This notice records provenance and gives credit, but it is not a substitute for
a licence.

If you intend to redistribute PWS publicly, please contact the upstream author
first to agree licensing terms, or replace the reused files listed above with
independent implementations.

## Other third-party components

- Weather data: [Pirate Weather](https://pirateweather.net/)
- Radar imagery: [NOAA / National Weather Service](https://radar.weather.gov/)
  (public domain US government work) and [RainViewer](https://www.rainviewer.com/)
- Base map tiles: [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
- Typeface: [Inter](https://rsms.me/inter/) by Rasmus Andersson, SIL Open Font
  License 1.1 (full text in `assets/fonts/Inter-LICENSE.txt`)
