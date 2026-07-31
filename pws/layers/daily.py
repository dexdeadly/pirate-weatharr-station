"""Seven-day forecast strip."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/daily.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from typing import Any, Callable, Dict, List

from PIL import ImageDraw

from pws import theme
from pws.core.layer import Layer
from pws.layers.anim_icons import AnimatedIconsMixin


class DailyLayer(AnimatedIconsMixin, Layer):
    """
    Seven day cards, each with an icon, high/low and precipitation chance.

    A shared temperature range bar runs through every card so the week's warm
    and cool ends read at a glance rather than requiring the viewer to compare
    numbers - the bars are scaled against the min/max across the whole week.
    """

    name = "daily"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_days: Callable[[], List[Dict[str, Any]]],
        min_interval: float = 30.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_days = get_days
        self._init_icons()
        self.min_interval = self._icon_interval()

    def tick(self, now: float):
        try:
            days = self.get_days() or []
        except Exception:
            days = []

        state = tuple(tuple(sorted((k, str(v)) for k, v in d.items())) for d in days)
        return self._render_with_icons(now, state, lambda: self._paint(days))

    def _paint(self, days: List[Dict[str, Any]]) -> None:
        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        draw = ImageDraw.Draw(surface, "RGBA")
        w, h = surface.size

        if not days:
            theme.card(surface, (0, 0, w, h), radius=self.s(theme.RADIUS_CARD, 1))
            draw = ImageDraw.Draw(surface, "RGBA")
            draw.text((self.s(32), self.s(28)), "Forecast data unavailable",
                      font=theme.font(self.s(34, 12), "medium"), fill=theme.TEXT_MUTED)
            return

        days = days[:7]
        count = len(days)
        gap = self.s(14, 1)
        card_w = (w - gap * (count - 1)) // count

        # Shared scale across the week for the range bars.
        highs = [d.get("high_f") for d in days if isinstance(d.get("high_f"), (int, float))]
        lows = [d.get("low_f") for d in days if isinstance(d.get("low_f"), (int, float))]
        span_min = min(lows) if lows else 0.0
        span_max = max(highs) if highs else 1.0
        if span_max - span_min < 8:
            mid = (span_max + span_min) / 2
            span_min, span_max = mid - 4, mid + 4
        span = max(1e-6, span_max - span_min)

        # Size the cards to their content and centre the row vertically, rather
        # than stretching them the full height and leaving dead space below.
        name_font = theme.font(self.s(28, 11), "bold")
        date_font = theme.font(self.s(19, 8), "medium")
        hi_font = theme.font(self.s(52, 15), "black")
        lo_font = theme.font(self.s(30, 11), "semibold")
        stat_label_font = theme.font(self.s(16, 7), "semibold")
        stat_value_font = theme.font(self.s(20, 8), "bold")

        # Secondary elements shown on every card. Each entry is
        # (label, dict key, optional suffix key, accent colour).
        stat_rows = [
            ("Precip", "precip_display", None, theme.PRECIP),
            ("Humidity", "humidity_display", None, theme.CYAN),
            ("Wind", "wind_display", "wind_unit", theme.LIME),
            ("Gusts", "gust_display", "wind_unit", theme.LIME),
            ("Cloud", "cloud_display", None, theme.CLOUD),
            ("UV Index", "uv_display", None, theme.AMBER),
        ]
        stat_h = theme.line_height(stat_value_font) + self.s(10)

        icon_size = min(self.s(96, 1), max(self.s(44, 1), card_w // 2))
        needed = (
            self.s(20)
            + theme.line_height(name_font) - self.s(2)
            + theme.line_height(date_font) + self.s(6)
            + icon_size + self.s(10)
            + theme.line_height(hi_font) - self.s(4)
            + theme.line_height(lo_font) + self.s(10)
            + self.s(8, 1) + self.s(14)
            + self.s(2, 1) + self.s(12)          # divider + gap
            + stat_h * len(stat_rows)
            + self.s(16)
        )
        card_h = min(h, needed)
        top = max(0, (h - card_h) // 2)
        bottom = top + card_h

        for index, day in enumerate(days):
            x0 = index * (card_w + gap)
            x1 = x0 + card_w
            is_today = index == 0

            theme.card(
                surface, (x0, top, x1, bottom),
                radius=self.s(20, 1),
                fill=theme.CARD_FILL_RAISED if is_today else theme.CARD_FILL,
                gradient_to=theme.CARD_FILL if is_today else theme.CARD_FILL_SUNKEN,
                border=theme.with_alpha(theme.ACCENT, 150) if is_today else theme.CARD_BORDER,
                border_width=self.s(2, 1),
                shadow_spread=self.s(8, 1),
            )
            draw = ImageDraw.Draw(surface, "RGBA")
            cx = (x0 + x1) // 2
            cursor = top + self.s(20)

            # Day name + date
            theme.text_center(draw, cx, cursor, str(day.get("name") or ""),
                              name_font, fill=theme.ACCENT if is_today else theme.TEXT)
            cursor += theme.line_height(name_font) - self.s(2)
            if day.get("date"):
                theme.text_center(draw, cx, cursor, str(day.get("date")).upper(),
                                  date_font, fill=theme.TEXT_DIM)
                cursor += theme.line_height(date_font) + self.s(6)

            # Icon slot (drawn per animation frame, not here)
            self._register_icon(cx - icon_size // 2, cursor, icon_size,
                                str(day.get("icon") or "clear-day"))
            cursor += icon_size + self.s(10)

            # High
            high_f = day.get("high_f")
            high_txt = self._deg(day.get("high"))
            theme.text_center(draw, cx, cursor, high_txt, hi_font,
                              fill=theme.temp_color(high_f))
            cursor += theme.line_height(hi_font) - self.s(4)

            # Low
            low_f = day.get("low_f")
            theme.text_center(draw, cx, cursor, self._deg(day.get("low")), lo_font,
                              fill=theme.with_alpha(theme.temp_color(low_f), 205))
            cursor += theme.line_height(lo_font) + self.s(10)

            # Range bar
            bar_h = self.s(8, 1)
            bar_x0 = x0 + self.s(20)
            bar_x1 = x1 - self.s(20)
            if bar_x1 > bar_x0 and cursor + bar_h < bottom - self.s(36):
                theme.pill(draw, (bar_x0, cursor, bar_x1, cursor + bar_h),
                           fill=theme.with_alpha(theme.TEXT_DIM, 60))
                if isinstance(high_f, (int, float)) and isinstance(low_f, (int, float)):
                    total = bar_x1 - bar_x0
                    fx0 = bar_x0 + int(total * ((low_f - span_min) / span))
                    fx1 = bar_x0 + int(total * ((high_f - span_min) / span))
                    if fx1 - fx0 < self.s(6, 1):
                        fx1 = fx0 + self.s(6, 1)
                    theme.pill(draw, (fx0, cursor, min(fx1, bar_x1), cursor + bar_h),
                               fill=theme.temp_color((high_f + low_f) / 2))
                cursor += bar_h + self.s(12)

            # Divider, then the secondary element list
            if cursor + self.s(20) < bottom:
                draw.line((x0 + self.s(18), cursor, x1 - self.s(18), cursor),
                          fill=theme.CARD_BORDER, width=self.s(2, 1))
                cursor += self.s(12)

            label_x = x0 + self.s(16)
            value_x = x1 - self.s(16)
            for label_text, key, suffix_key, color in stat_rows:
                if cursor + stat_h > bottom:
                    break
                value = str(day.get(key) or "--")
                suffix = str(day.get(suffix_key) or "") if suffix_key else ""
                if suffix and value not in ("--", "Calm"):
                    value = f"{value} {suffix}"
                # Share one centre line so the differing font sizes stay level.
                row_centre = cursor + stat_h / 2.0 - self.s(5)
                theme.label(draw,
                            (label_x, theme.top_for_center(stat_label_font, row_centre)),
                            label_text, stat_label_font, fill=theme.TEXT_DIM,
                            tracking=self.s(1, 1))
                theme.text_right(draw,
                                 (value_x, theme.top_for_center(stat_value_font, row_centre)),
                                 value, stat_value_font, fill=color)
                cursor += stat_h

    @staticmethod
    def _deg(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{int(round(value))}°"
        return "--°"
