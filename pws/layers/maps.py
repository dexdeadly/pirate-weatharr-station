"""
Regional and forecast map layers.

Both pages plot city markers over an OpenStreetMap base tile composite, so the
projection, base-map handling and label collision logic live in one shared base
class. Markers are drawn as temperature-tinted chips rather than stroked text,
which reads far better over busy map imagery.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from pws import theme
from pws.core.layer import Layer
from pws.layers.anim_icons import AnimatedIconsMixin

Bounds = Tuple[float, float, float, float]


class _MapLayerBase(AnimatedIconsMixin, Layer):
    """Common base: base map, projection, marker placement."""

    #: Key holding the display temperature in each point dict.
    temp_key = "temp"
    #: Key holding the condition text in each point dict.
    condition_key = "condition"
    empty_message = "Map data unavailable"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_points: Callable[[], List[Dict[str, Any]]],
        get_map: Callable[[], Optional[Image.Image]],
        get_bounds: Callable[[], Optional[Bounds]],
        min_interval: float = 15.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_points = get_points
        self.get_map = get_map
        self.get_bounds = get_bounds
        self._mask: Image.Image | None = None
        self._init_icons()
        self.min_interval = self._icon_interval()

    # -- helpers ----------------------------------------------------------

    def _corner_mask(self) -> Image.Image:
        if self._mask is None or self._mask.size != self.surface.size:
            mask = Image.new("L", self.surface.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, self.surface.width - 1, self.surface.height - 1),
                radius=theme.radius_of(self.s(theme.RADIUS_CARD)), fill=255,
            )
            self._mask = mask
        return self._mask

    def _safe(self, fn, default=None):
        if not callable(fn):
            return default
        try:
            return fn()
        except Exception:
            return default

    def _paint_base(self, surface: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        base_img = self._safe(self.get_map)
        if base_img is not None:
            try:
                base = base_img.convert("RGBA")
                if base.size != surface.size:
                    base = base.resize(surface.size, Image.LANCZOS)
                # Darken and desaturate slightly so markers stay legible.
                tint = Image.new("RGBA", base.size, (10, 15, 32, 120))
                base = Image.alpha_composite(base, tint)
                surface.paste(base, (0, 0), self._corner_mask())
                return
            except Exception:
                pass

        # Fallback: graticule over the standard card.
        theme.card(surface, (0, 0, surface.width, surface.height),
                   radius=self.s(theme.RADIUS_CARD, 1),
                   fill=theme.CARD_FILL_SUNKEN)
        d = ImageDraw.Draw(surface, "RGBA")
        grid = theme.with_alpha(theme.TEXT_DIM, 45)
        for frac in (0.2, 0.4, 0.6, 0.8):
            y = int(frac * surface.height)
            x = int(frac * surface.width)
            d.line((0, y, surface.width, y), fill=grid, width=self.s(2, 1))
            d.line((x, 0, x, surface.height), fill=grid, width=self.s(2, 1))

    def _resolve_bounds(self, points: Sequence[dict]) -> Bounds:
        bounds = self._safe(self.get_bounds)
        if bounds and len(bounds) == 4:
            return tuple(float(v) for v in bounds)  # type: ignore[return-value]
        lats = [p["lat"] for p in points if p.get("lat") is not None]
        lons = [p["lon"] for p in points if p.get("lon") is not None]
        if not lats or not lons:
            return (0.0, 0.0, 1.0, 1.0)
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)
        if lat_max - lat_min < 0.5:
            lat_min -= 0.25
            lat_max += 0.25
        if lon_max - lon_min < 0.5:
            lon_min -= 0.25
            lon_max += 0.25
        return (lat_min, lon_min, lat_max, lon_max)

    # -- render -----------------------------------------------------------

    def tick(self, now: float):
        points = self._safe(self.get_points, []) or []
        base = self._safe(self.get_map)
        state = (
            tuple(tuple(sorted((k, str(v)) for k, v in p.items())) for p in points),
            None if base is None else base.size,
            str(self._safe(self.get_bounds)),
        )
        return self._render_with_icons(now, state, lambda: self._paint(points))

    def _paint(self, points):
        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        draw = ImageDraw.Draw(surface, "RGBA")

        self._paint_base(surface, draw)
        draw = ImageDraw.Draw(surface, "RGBA")

        # Hairline frame
        draw.rounded_rectangle(
            (0, 0, surface.width - 1, surface.height - 1),
            radius=theme.radius_of(self.s(theme.RADIUS_CARD)),
            outline=theme.CARD_BORDER_STRONG, width=self.s(2, 1),
        )

        if not points:
            draw.text((self.s(32), self.s(28)), self.empty_message,
                      font=theme.font(self.s(32, 12), "medium"), fill=theme.TEXT_MUTED)
            return

        lat_min, lon_min, lat_max, lon_max = self._resolve_bounds(points)
        lat_span = max(1e-6, lat_max - lat_min)
        lon_span = max(1e-6, lon_max - lon_min)
        w, h = surface.size
        inset = self.s(70, 10)

        def project(lat: float, lon: float) -> tuple[int, int]:
            x = int(((lon - lon_min) / lon_span) * w)
            y = h - int(((lat - lat_min) / lat_span) * h)
            return (max(inset, min(w - inset, x)), max(inset, min(h - inset, y)))

        placed: list[tuple[int, int, int, int]] = []
        for point in points:
            lat, lon = point.get("lat"), point.get("lon")
            if lat is None or lon is None:
                continue
            self._draw_marker(surface, project(float(lat), float(lon)), point, placed)

    # -- markers ----------------------------------------------------------

    def _draw_marker(self, surface: Image.Image, xy: tuple[int, int],
                     point: Dict[str, Any],
                     placed: list[tuple[int, int, int, int]]) -> None:
        draw = ImageDraw.Draw(surface, "RGBA")
        x, y = xy

        temp_f = point.get("temp_f")
        color = theme.temp_color(temp_f)

        # Location pin: glow ring + solid centre.
        ring = self.s(15, 4)
        draw.ellipse((x - ring, y - ring, x + ring, y + ring),
                     fill=theme.with_alpha(color, 70))
        dot = self.s(7, 2)
        draw.ellipse((x - dot, y - dot, x + dot, y + dot), fill=(255, 255, 255, 255),
                     outline=tuple(color), width=self.s(3, 1))

        name = str(point.get("name") or "")
        temp = str(point.get(self.temp_key) or "--")
        name_font = theme.font(self.s(24, 10), "bold")
        temp_font = theme.font(self.s(30, 11), "black")

        icon_size = self.s(40, 1)

        name_w = theme.text_width(draw, name, name_font)
        temp_w = theme.text_width(draw, temp, temp_font)
        pad = self.s(12, 2)
        chip_w = pad * 2 + icon_size + self.s(10) + max(name_w, temp_w)
        chip_h = pad * 2 + self.s(46, 1)

        # Prefer upper-right of the pin; flip or nudge on collision.
        candidates = [
            (x + self.s(20), y - chip_h // 2),
            (x - chip_w - self.s(20), y - chip_h // 2),
            (x + self.s(20), y - chip_h - self.s(18)),
            (x + self.s(20), y + self.s(18)),
            (x - chip_w - self.s(20), y + self.s(18)),
        ]
        cx = cy = None
        for candidate_x, candidate_y in candidates:
            box = (candidate_x, candidate_y, candidate_x + chip_w, candidate_y + chip_h)
            if box[0] < self.s(6) or box[2] > surface.width - self.s(6):
                continue
            if box[1] < self.s(6) or box[3] > surface.height - self.s(6):
                continue
            if any(self._overlaps(box, other) for other in placed):
                continue
            cx, cy = candidate_x, candidate_y
            break
        if cx is None:
            return  # No clean placement; the pin alone still marks the city.

        box = (cx, cy, cx + chip_w, cy + chip_h)
        placed.append(box)

        theme.card(surface, box, radius=self.s(14, 1),
                   fill=(10, 15, 32, 208),
                   border=theme.with_alpha(color, 170),
                   border_width=self.s(2, 1),
                   shadow=True, shadow_spread=self.s(6, 1), top_highlight=False)
        draw = ImageDraw.Draw(surface, "RGBA")

        self._register_icon(cx + pad, cy + (chip_h - icon_size) // 2, icon_size,
                            str(point.get("icon") or "clear-day"))
        text_x = cx + pad + icon_size + self.s(10)
        draw.text((text_x, cy + pad - self.s(2)), name, font=name_font, fill=theme.TEXT)
        draw.text((text_x, cy + pad + self.s(22)), temp, font=temp_font, fill=color)

    @staticmethod
    def _overlaps(a: Sequence[int], b: Sequence[int]) -> bool:
        return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


class RegionalLayer(_MapLayerBase):
    """Current conditions across nearby cities."""

    name = "regional"
    temp_key = "temp"
    condition_key = "condition"
    empty_message = "Regional data unavailable"


class ForecastMapLayer(_MapLayerBase):
    """Forecast highs across nearby cities."""

    name = "forecast_map"
    temp_key = "forecast_temp"
    condition_key = "forecast_short"
    empty_message = "Forecast map data unavailable"
