"""Narrative forecast panels for today and tomorrow."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/forecast_text.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from typing import Any, Callable, Dict, List

from PIL import ImageDraw

from pws import theme
from pws.core.layer import Layer
from pws.layers.anim_icons import AnimatedIconsMixin


class ForecastTextLayer(AnimatedIconsMixin, Layer):
    """
    Two side-by-side narrative panels.

    Pirate Weather returns a terse phrase rather than the NWS's paragraph-length
    prose, so the body text here is composed in ``normalize._narrative`` from the
    numeric daily fields. Each panel also carries a compact stat row.
    """

    name = "forecast_text"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_periods: Callable[[], List[Dict[str, Any]]],
        min_interval: float = 30.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_periods = get_periods
        self._init_icons()
        self.min_interval = self._icon_interval()

    def tick(self, now: float):
        try:
            periods = self.get_periods() or []
        except Exception:
            periods = []

        state = tuple(tuple(sorted((k, str(v)) for k, v in p.items())) for p in periods)
        return self._render_with_icons(now, state, lambda: self._paint(periods))

    def _paint(self, periods: List[Dict[str, Any]]) -> None:
        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        draw = ImageDraw.Draw(surface, "RGBA")
        w, h = surface.size

        if not periods:
            theme.card(surface, (0, 0, w, h), radius=self.s(theme.RADIUS_CARD, 1))
            draw = ImageDraw.Draw(surface, "RGBA")
            draw.text((self.s(32), self.s(28)), "No forecast available",
                      font=theme.font(self.s(34, 12), "medium"), fill=theme.TEXT_MUTED)
            return

        periods = periods[:2]
        count = len(periods)
        gap = self.s(24, 1)
        panel_w = (w - gap * (count - 1)) // count

        for index, period in enumerate(periods):
            x0 = index * (panel_w + gap)
            self._draw_panel(surface, (x0, 0, x0 + panel_w, h), period,
                             primary=index == 0)

    # -- panel ------------------------------------------------------------

    def _draw_panel(self, surface, box, period: Dict[str, Any], *, primary: bool) -> None:
        x0, y0, x1, y1 = box
        theme.card(
            surface, box,
            radius=self.s(22, 1),
            fill=theme.CARD_FILL_RAISED if primary else theme.CARD_FILL,
            gradient_to=theme.CARD_FILL if primary else theme.CARD_FILL_SUNKEN,
            border=theme.with_alpha(theme.ACCENT, 140) if primary else theme.CARD_BORDER,
            border_width=self.s(2, 1),
            shadow_spread=self.s(12, 2),
        )
        draw = ImageDraw.Draw(surface, "RGBA")

        pad = self.s(30)
        inner_w = (x1 - x0) - pad * 2
        cursor = y0 + self.s(26)

        # Title + icon
        title_font = theme.font(self.s(36, 12), "bold")
        theme.tracked_text(draw, (x0 + pad, cursor), str(period.get("name") or "").upper(),
                           title_font, fill=theme.ACCENT if primary else theme.TEXT,
                           tracking=self.s(3, 1))

        icon_size = self.s(84, 1)
        self._register_icon(x1 - pad - icon_size, cursor - self.s(12), icon_size,
                            str(period.get("icon") or "clear-day"))

        cursor += theme.line_height(title_font) + self.s(10)

        # High / low
        hi_font = theme.font(self.s(66, 18), "black")
        lo_font = theme.font(self.s(30, 11), "semibold")
        high_color = theme.temp_color(period.get("high_f"))
        draw.text((x0 + pad, cursor), str(period.get("high") or "--°"),
                  font=hi_font, fill=high_color)
        high_w = theme.text_width(draw, str(period.get("high") or "--°"), hi_font)
        draw.text((x0 + pad + high_w + self.s(16), cursor + self.s(26)),
                  f"/ {period.get('low', '--°')}", font=lo_font, fill=theme.TEXT_MUTED)
        cursor += theme.line_height(hi_font) + self.s(8)

        # Stat grid: two rows of four, covering every element the daily block
        # exposes beyond the headline temperatures.
        stats = [
            ("Wind", f"{period.get('wind_dir', '')} {period.get('wind', '--')}".strip()),
            ("Gusts", str(period.get("gust") or "--")),
            ("Precip", self._pct(period.get("precip"))),
            ("Humidity", str(period.get("humidity") or "--")),
            ("Dew Point", str(period.get("dew") or "--")),
            ("Cloud", str(period.get("cloud") or "--")),
            ("UV Index", str(period.get("uv") or "--")),
            ("Pressure", str(period.get("pressure") or "--")),
        ]
        stat_label = theme.font(self.s(17, 8), "semibold")
        stat_value = theme.font(self.s(24, 10), "bold")
        cols = 4
        col_w = inner_w // cols
        row_h = self.s(56)
        for i, (name, value) in enumerate(stats):
            cxx = x0 + pad + (i % cols) * col_w
            cyy = cursor + (i // cols) * row_h
            theme.label(draw, (cxx, cyy), name, stat_label,
                        fill=theme.TEXT_DIM, tracking=self.s(2, 1))
            draw.text((cxx, cyy + self.s(20)), value, font=stat_value, fill=theme.TEXT)
        cursor += row_h * 2 + self.s(8)

        # Feels-like and accumulation, only when they add something.
        extra_font = theme.font(self.s(20, 8), "medium")
        extras = []
        feels_high = str(period.get("feels_high") or "").strip()
        if feels_high and feels_high != "--°":
            extras.append(f"Feels like {feels_high} / {period.get('feels_low', '--°')}")
        accumulation = str(period.get("accumulation") or "--").strip()
        if accumulation and accumulation != "--":
            ptype = str(period.get("precip_type") or "").strip()
            ptype = "" if ptype.lower() in ("none", "") else f"{ptype} "
            extras.append(f"{ptype}accumulation {accumulation}")
        visibility = str(period.get("visibility") or "--").strip()
        if visibility and visibility != "--":
            extras.append(f"Visibility {visibility}")
        if extras:
            theme.label(draw, (x0 + pad, cursor), "  ·  ".join(extras), extra_font,
                        fill=theme.TEXT_MUTED, tracking=self.s(1, 1))
            cursor += theme.line_height(extra_font) + self.s(12)

        # Divider
        draw.line((x0 + pad, cursor, x1 - pad, cursor),
                  fill=theme.CARD_BORDER, width=self.s(2, 1))
        cursor += self.s(20)

        # Narrative body
        body_font = theme.font(self.s(29, 11), "regular")
        line_h = theme.line_height(body_font) + self.s(8)
        max_lines = max(1, (y1 - self.s(24) - cursor) // max(1, line_h))
        text = str(period.get("detailed") or period.get("short") or "")
        for line in theme.wrap(draw, text, body_font, inner_w, max_lines=int(max_lines)):
            draw.text((x0 + pad, cursor), line, font=body_font, fill=theme.TEXT)
            cursor += line_h

        # Sun times footer
        foot_font = theme.font(self.s(21, 9), "semibold")
        foot_y = y1 - self.s(38)
        if foot_y > cursor:
            theme.label(draw, (x0 + pad, foot_y),
                        f"Sunrise {period.get('sunrise', '--')}", foot_font,
                        fill=theme.AMBER, tracking=self.s(1, 1))
            moon = str(period.get("moon_phase") or "").strip()
            if moon and moon != "--":
                mid_font = theme.font(self.s(20, 8), "medium")
                mw = theme.tracked_width(draw, moon.upper(), mid_font, self.s(1, 1))
                theme.tracked_text(draw, ((x0 + x1) // 2 - mw // 2, foot_y),
                                   moon.upper(), mid_font, fill=theme.VIOLET,
                                   tracking=self.s(1, 1))
            theme.text_right(draw, (x1 - pad, foot_y),
                             f"SUNSET {period.get('sunset', '--')}".upper(),
                             foot_font, fill=theme.ROSE)

    @staticmethod
    def _pct(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{int(round(value))}%"
        return "--"
