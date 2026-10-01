"""
Surf report page.

Top row: estimated surf height with a conditions rating, a 2x2 grid of swell /
wind / water-temperature tiles, and the next high/low tides. Bottom row: a
five-day wave-height outlook. Data comes from pws/surf.py (Open-Meteo Marine
and NOAA CO-OPS), never from the Pirate Weather quota.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

from PIL import ImageDraw

from pws import theme
from pws.core.layer import Layer

_RATING_COLORS = {
    "FLAT": theme.TEXT_DIM,
    "POOR": theme.ROSE,
    "FAIR": theme.AMBER,
    "GOOD": theme.ALERT_NONE,
    "EPIC": theme.VIOLET,
}


def _arrow(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float,
           from_deg: Optional[float], color) -> None:
    """Arrow showing where the swell/wind is travelling (meteorological 'from' + 180)."""
    if from_deg is None:
        return
    heading = math.radians((from_deg + 180.0) % 360.0)
    dx, dy = math.sin(heading), -math.cos(heading)
    tip = (cx + dx * size, cy + dy * size)
    tail = (cx - dx * size, cy - dy * size)
    draw.line((tail, tip), fill=color, width=max(2, int(size / 4)))
    # Arrowhead: two short strokes back from the tip.
    for side in (-1, 1):
        ang = heading + math.pi + side * 0.5
        draw.line((tip, (tip[0] + math.sin(ang) * size * 0.7,
                         tip[1] - math.cos(ang) * size * 0.7)),
                  fill=color, width=max(2, int(size / 4)))


class SurfLayer(Layer):
    name = "surf"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_report: Callable[[], Optional[Dict[str, Any]]],
        min_interval: float = 20.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_report = get_report
        self._state: Any = None

    def tick(self, now: float):
        try:
            report = self.get_report() or {}
        except Exception:
            report = {}
        # Reports are rebuilt only on data refresh; skip identical repaints.
        state = repr(sorted(report.items()))
        if state == self._state and self._last_hash is not None:
            return []
        self._state = state

        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        w, h = surface.size
        draw = ImageDraw.Draw(surface, "RGBA")

        if not report.get("available"):
            theme.card(surface, (0, 0, w, h), fill=theme.CARD_FILL,
                       gradient_to=theme.CARD_FILL_SUNKEN, border=theme.CARD_BORDER,
                       border_width=self.s(2, 1))
            draw = ImageDraw.Draw(surface, "RGBA")
            message = report.get("message") or "Surf report loading..."
            draw.text((self.s(32), self.s(28)), message,
                      font=theme.font(self.s(32, 12), "medium"), fill=theme.TEXT_MUTED)
            return self._mark_all_dirty_if_changed()

        gap = self.s(22, 1)
        top_h = int(h * 0.52)
        hero_w = int(w * 0.30)
        tide_w = int(w * 0.27)
        mid_w = w - hero_w - tide_w - gap * 2

        self._hero(surface, (0, 0, hero_w, top_h), report)
        self._tiles(surface, (hero_w + gap, 0, hero_w + gap + mid_w, top_h), report)
        self._tides(surface, (w - tide_w, 0, w, top_h), report)
        self._outlook(surface, (0, top_h + gap, w, h), report)
        return self._mark_all_dirty_if_changed()

    # -- panels -----------------------------------------------------------

    def _panel(self, surface, box) -> ImageDraw.ImageDraw:
        theme.card(surface, box, fill=theme.CARD_FILL, gradient_to=theme.CARD_FILL_SUNKEN,
                   border=theme.CARD_BORDER, border_width=self.s(2, 1),
                   shadow_spread=self.s(12, 2))
        return ImageDraw.Draw(surface, "RGBA")

    def _hero(self, surface, box, report: dict) -> None:
        x0, y0, x1, y1 = box
        draw = self._panel(surface, box)
        pad = self.s(30)
        label_font = theme.font(self.s(20, 8), "semibold")
        theme.label(draw, (x0 + pad, y0 + pad), "ESTIMATED SURF", label_font,
                    fill=theme.TEXT_DIM, tracking=self.s(3, 1))
        spot = str(report.get("spot") or "").upper()
        if spot:
            spot_font = theme.font(self.s(24, 9), "bold")
            lines = theme.wrap(draw, spot, spot_font, (x1 - x0) - pad * 2, max_lines=1)
            if lines:
                draw.text((x0 + pad, y0 + pad + self.s(28)), lines[0],
                          font=spot_font, fill=theme.ACCENT)

        big = theme.font(self.s(104, 24), "black")
        unit_font = theme.font(self.s(36, 12), "bold")
        rng = str(report.get("surf_range") or "--")
        by = y0 + pad + self.s(64)
        draw.text((x0 + pad, by), rng, font=big, fill=theme.TEXT)
        rw = theme.text_width(draw, rng, big)
        draw.text((x0 + pad + rw + self.s(10), by + self.s(52)),
                  str(report.get("len_unit") or ""), font=unit_font, fill=theme.TEXT_MUTED)

        rating = str(report.get("rating") or "--")
        ry = by + theme.line_height(big) + self.s(10)
        theme.badge(surface, draw, (x0 + pad, ry), rating, scale=self.scale * 1.3,
                    fill=_RATING_COLORS.get(rating, theme.ACCENT))

        detail_font = theme.font(self.s(24, 9), "medium")
        detail = (f"Waves {report.get('wave_height', '--')} @ "
                  f"{report.get('wave_period', '--')} {report.get('wave_dir', '')}")
        draw.text((x0 + pad, y1 - pad - theme.line_height(detail_font)), detail,
                  font=detail_font, fill=theme.TEXT_MUTED)

    def _tiles(self, surface, box, report: dict) -> None:
        x0, y0, x1, y1 = box
        swells = list(report.get("swells") or [])
        tiles = []
        for swell in swells[:2]:
            tiles.append((f"{swell['label']} Swell",
                          f"{swell['height']} {swell['period']}",
                          swell["dir"], swell.get("deg"), theme.CYAN))
        while len(tiles) < 2:
            tiles.append(("Swell", "--", "", None, theme.CYAN))
        wind = str(report.get("wind") or "--")
        gust = str(report.get("wind_gust") or "")
        tiles.append(("Wind", wind, gust, None, theme.CLOUD))
        tiles.append(("Water Temp", str(report.get("water_temp") or "--"), "", None, theme.PRECIP))

        gap = self.s(16, 1)
        tw = ((x1 - x0) - gap) // 2
        th = ((y1 - y0) - gap) // 2
        label_font = theme.font(self.s(19, 8), "semibold")
        value_font = theme.font(self.s(38, 12), "bold")
        sub_font = theme.font(self.s(22, 9), "medium")
        for i, (name, value, sub, deg, accent) in enumerate(tiles):
            tx = x0 + (i % 2) * (tw + gap)
            ty = y0 + (i // 2) * (th + gap)
            theme.card(surface, (tx, ty, tx + tw, ty + th), fill=theme.CARD_FILL_SUNKEN,
                       border=theme.CARD_BORDER, border_width=self.s(2, 1), shadow=False)
            draw = ImageDraw.Draw(surface, "RGBA")
            pad = self.s(20)
            theme.accent_rule(draw, tx + pad, ty + pad, self.s(4), th - pad * 2, color=accent)
            text_x = tx + pad + self.s(18)
            theme.label(draw, (text_x, ty + pad), name.upper(), label_font,
                        fill=theme.TEXT_DIM, tracking=self.s(2, 1))
            vy = ty + pad + self.s(30)
            lines = theme.wrap(draw, value, value_font, tw - (text_x - tx) - self.s(60), max_lines=1)
            draw.text((text_x, vy), lines[0] if lines else value, font=value_font, fill=theme.TEXT)
            if sub:
                draw.text((text_x, vy + theme.line_height(value_font) + self.s(4)), sub,
                          font=sub_font, fill=theme.TEXT_MUTED)
            if deg is not None:
                size = self.s(18, 4)
                _arrow(draw, tx + tw - pad - size, ty + th / 2, size, deg, accent)

    def _tides(self, surface, box, report: dict) -> None:
        x0, y0, x1, y1 = box
        draw = self._panel(surface, box)
        pad = self.s(28)
        label_font = theme.font(self.s(20, 8), "semibold")
        theme.label(draw, (x0 + pad, y0 + pad), "TIDES", label_font,
                    fill=theme.TEXT_DIM, tracking=self.s(3, 1))
        tides = list(report.get("tides") or [])
        if not tides:
            msg_font = theme.font(self.s(24, 9), "medium")
            y = y0 + pad + self.s(44)
            for line in theme.wrap(draw, "No NOAA tide station near this spot "
                                   "(tide predictions cover US coasts only).",
                                   msg_font, (x1 - x0) - pad * 2, max_lines=4):
                draw.text((x0 + pad, y), line, font=msg_font, fill=theme.TEXT_MUTED)
                y += theme.line_height(msg_font) + self.s(4)
            return

        kind_font = theme.font(self.s(22, 9), "bold")
        time_font = theme.font(self.s(32, 11), "bold")
        h_font = theme.font(self.s(24, 9), "medium")
        list_top = y0 + pad + self.s(40)
        station = str(report.get("tide_station") or "")
        st_font = theme.font(self.s(18, 8), "medium")
        list_bottom = y1 - pad - (theme.line_height(st_font) + self.s(8) if station else 0)
        row_h = (list_bottom - list_top) // max(1, len(tides))
        for i, tide in enumerate(tides):
            cy = list_top + row_h * i + row_h / 2
            high = tide.get("kind") == "HIGH"
            color = theme.PRECIP if high else theme.TEXT_MUTED
            kind = tide.get("kind", "")
            draw.text((x0 + pad, theme.top_for_center(kind_font, cy)), kind,
                      font=kind_font, fill=color)
            when = tide.get("time", "--")
            if tide.get("day"):
                when = f"{tide['day']} {when}"
            draw.text((x0 + pad + self.s(86), theme.top_for_center(time_font, cy)), when,
                      font=time_font, fill=theme.TEXT)
            theme.text_right(draw, (x1 - pad, theme.top_for_center(h_font, cy)),
                             str(tide.get("height", "")), h_font, fill=theme.TEXT_MUTED)
        if station:
            lines = theme.wrap(draw, station.upper(), st_font, (x1 - x0) - pad * 2, max_lines=1)
            if lines:
                theme.label(draw, (x0 + pad, y1 - pad - theme.line_height(st_font)),
                            lines[0], st_font, fill=theme.TEXT_DIM, tracking=self.s(1, 1))

    def _outlook(self, surface, box, report: dict) -> None:
        x0, y0, x1, y1 = box
        draw = self._panel(surface, box)
        pad = self.s(28)
        label_font = theme.font(self.s(20, 8), "semibold")
        theme.label(draw, (x0 + pad, y0 + pad), "5-DAY WAVE OUTLOOK", label_font,
                    fill=theme.TEXT_DIM, tracking=self.s(3, 1))
        src_font = theme.font(self.s(18, 8), "medium")
        theme.text_right(draw, (x1 - pad, y0 + pad), str(report.get("source") or ""),
                         src_font, fill=theme.TEXT_DIM)

        days = list(report.get("outlook") or [])[:5]
        if not days:
            return
        heights = [d.get("height") or 0.0 for d in days]
        top = max(heights) or 1.0
        n = len(days)
        col_gap = self.s(24, 1)
        col_w = ((x1 - x0) - pad * 2 - col_gap * (n - 1)) // n
        name_font = theme.font(self.s(22, 9), "bold")
        rng_font = theme.font(self.s(30, 11), "bold")
        meta_font = theme.font(self.s(20, 8), "medium")

        chart_top = y0 + pad + self.s(44)
        names_y = y1 - pad - theme.line_height(name_font)
        bar_bottom = names_y - self.s(12)
        bar_space = bar_bottom - chart_top - theme.line_height(rng_font) - theme.line_height(meta_font) - self.s(14)
        unit = str(report.get("len_unit") or "")
        for i, day in enumerate(days):
            cx0 = x0 + pad + i * (col_w + col_gap)
            frac = (day.get("height") or 0.0) / top
            bar_h = max(self.s(6, 2), int(bar_space * frac))
            bx0 = cx0 + col_w // 5
            bx1 = cx0 + col_w - col_w // 5
            by0 = bar_bottom - bar_h
            bar = theme.vertical_gradient((bx1 - bx0, bar_h), theme.CYAN,
                                          theme.with_alpha(theme.PRECIP, 140))
            surface.alpha_composite(bar, dest=(bx0, by0))
            draw = ImageDraw.Draw(surface, "RGBA")
            cx = cx0 + col_w // 2
            meta = " ".join(v for v in (day.get("period"), day.get("dir")) if v)
            theme.text_center(draw, cx, by0 - self.s(8) - theme.line_height(meta_font),
                              meta, meta_font, fill=theme.TEXT_MUTED)
            theme.text_center(draw, cx, by0 - self.s(10) - theme.line_height(meta_font)
                              - theme.line_height(rng_font),
                              f"{day.get('range', '--')} {unit}", rng_font, fill=theme.TEXT)
            theme.text_center(draw, cx, names_y, str(day.get("name") or ""), name_font,
                              fill=theme.TEXT_DIM)
