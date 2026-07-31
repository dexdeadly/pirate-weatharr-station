"""Hourly trend graph: temperature curve plus precipitation and cloud cover."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/hourly_graph.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from typing import Any, Callable, Dict, List

from PIL import ImageDraw

from pws import theme
from pws.core.layer import Layer


class HourlyGraphLayer(Layer):
    """
    Twelve-hour trend chart.

    Temperature is drawn as a glowing curve over a gradient area fill; cloud
    cover and precipitation probability share a right-hand percentage axis. All
    three series arrive in the single Pirate Weather hourly block.
    """

    name = "hourly_graph"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_points: Callable[[], List[Dict[str, Any]]],
        min_interval: float = 15.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_points = get_points

    def tick(self, now: float):
        try:
            points = self.get_points() or []
        except Exception:
            points = []

        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        w, h = surface.size

        theme.card(
            surface, (0, 0, w, h),
            radius=self.s(theme.RADIUS_CARD, 1),
            fill=theme.CARD_FILL,
            gradient_to=theme.CARD_FILL_SUNKEN,
            border=theme.CARD_BORDER,
            border_width=self.s(2, 1),
            shadow_spread=self.s(12, 2),
        )
        draw = ImageDraw.Draw(surface, "RGBA")

        if not points:
            draw.text((self.s(32), self.s(28)), "Hourly data unavailable",
                      font=theme.font(self.s(34, 12), "medium"), fill=theme.TEXT_MUTED)
            return self._mark_all_dirty_if_changed()

        # ---- legend ------------------------------------------------------
        legend_y = self.s(22)
        self._draw_legend(surface, draw, self.s(32), legend_y)

        # ---- plot area ---------------------------------------------------
        left = self.s(96, 1)
        right = w - self.s(96, 1)
        top = legend_y + self.s(52)
        bottom = h - self.s(66, 1)
        if right <= left or bottom <= top:
            return self._mark_all_dirty_if_changed()

        temps = [p.get("temp_f") for p in points if isinstance(p.get("temp_f"), (int, float))]
        if temps:
            t_min, t_max = min(temps), max(temps)
        else:
            t_min, t_max = 0.0, 100.0
        if t_max - t_min < 10:
            mid = (t_max + t_min) / 2
            t_min, t_max = mid - 5, mid + 5
        y_min, y_max = t_min - 3, t_max + 3
        y_span = max(1e-6, y_max - y_min)

        n = max(1, len(points) - 1)

        def x_for(i: int) -> int:
            return left + int((i / n) * (right - left))

        def y_for_temp(value: float) -> int:
            return int(bottom - ((value - y_min) / y_span) * (bottom - top))

        def y_for_pct(pct: float) -> int:
            return int(bottom - (max(0.0, min(100.0, pct)) / 100.0) * (bottom - top))

        # ---- gridlines + axes -------------------------------------------
        tick_font = theme.font(self.s(20, 8), "medium")
        for i in range(5):
            frac = i / 4
            y = int(bottom - frac * (bottom - top))
            draw.line((left, y, right, y),
                      fill=theme.with_alpha(theme.TEXT_DIM, 40 if i else 90),
                      width=self.s(2, 1))
            value = y_min + y_span * frac
            theme.text_right(draw, (left - self.s(14), y - self.s(11)),
                             f"{value:.0f}°", tick_font, fill=theme.TEXT_DIM)
            theme.text_right(draw, (right + self.s(52), y - self.s(11)),
                             f"{int(round(frac * 100))}%", tick_font,
                             fill=theme.with_alpha(theme.PRECIP, 190))

        # ---- series ------------------------------------------------------
        temp_pts, precip_pts, cloud_pts = [], [], []
        for i, p in enumerate(points):
            x = x_for(i)
            if isinstance(p.get("temp_f"), (int, float)):
                temp_pts.append((x, y_for_temp(float(p["temp_f"]))))
            if isinstance(p.get("precip"), (int, float)):
                precip_pts.append((x, y_for_pct(float(p["precip"]))))
            if isinstance(p.get("cloud"), (int, float)):
                cloud_pts.append((x, y_for_pct(float(p["cloud"]))))

        # Cloud cover sits furthest back as a soft band.
        if len(cloud_pts) > 1:
            theme.area_fill(surface, cloud_pts, bottom, theme.CLOUD, alpha_top=34)
            draw = ImageDraw.Draw(surface, "RGBA")
            theme.sparkline(draw, cloud_pts, color=theme.with_alpha(theme.CLOUD, 190),
                            width=self.s(3, 1), glow=False)

        if len(precip_pts) > 1:
            theme.area_fill(surface, precip_pts, bottom, theme.PRECIP, alpha_top=70)
            draw = ImageDraw.Draw(surface, "RGBA")
            theme.sparkline(draw, precip_pts, color=theme.PRECIP,
                            width=self.s(4, 1), glow=False)

        if len(temp_pts) > 1:
            theme.area_fill(surface, temp_pts, bottom, theme.AMBER, alpha_top=52)
            draw = ImageDraw.Draw(surface, "RGBA")
            theme.sparkline(draw, temp_pts, color=theme.AMBER, width=self.s(6, 1))

        # Temperature nodes + value labels
        value_font = theme.font(self.s(22, 9), "bold")
        dot = self.s(7, 2)
        for i, (x, y) in enumerate(temp_pts):
            draw.ellipse((x - dot, y - dot, x + dot, y + dot),
                         fill=(255, 255, 255, 255),
                         outline=theme.with_alpha(theme.AMBER, 220),
                         width=self.s(3, 1))
            point = points[i] if i < len(points) else {}
            temp = point.get("temp")
            if isinstance(temp, (int, float)) and (i % 2 == 0 or i == len(temp_pts) - 1):
                theme.text_center(draw, x, y - self.s(38), f"{int(round(temp))}°",
                                  value_font, fill=theme.TEXT)

        # ---- x labels ----------------------------------------------------
        label_font = theme.font(self.s(22, 9), "semibold")
        label_y = bottom + self.s(16)
        for i, p in enumerate(points):
            text = str(p.get("label") or "")
            if not text:
                continue
            theme.text_center(draw, x_for(i), label_y, text, label_font,
                              fill=theme.TEXT_MUTED)

        return self._mark_all_dirty_if_changed()

    # -- legend -----------------------------------------------------------

    def _draw_legend(self, surface, draw, x: int, y: int) -> None:
        entries = (
            ("Temperature", theme.AMBER),
            ("Precip Chance", theme.PRECIP),
            ("Cloud Cover", theme.CLOUD),
        )
        font = theme.font(self.s(21, 9), "semibold")
        cursor = x
        for name, color in entries:
            swatch = self.s(16, 4)
            theme.pill(draw, (cursor, y + self.s(4), cursor + swatch * 2, y + self.s(4) + swatch),
                       fill=tuple(color))
            cursor += swatch * 2 + self.s(10)
            width = theme.label(draw, (cursor, y), name, font,
                                fill=theme.TEXT_MUTED, tracking=self.s(2, 1))
            cursor += width + self.s(34)
