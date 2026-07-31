"""
Almanac / detail page.

This replaces the reference project's "latest observations" table. Pirate
Weather is a forecast model rather than a station network, so instead of listing
nearby METAR readings this page surfaces the astronomical, atmospheric and
air-quality fields that arrive in the same single API call - no extra quota.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from PIL import ImageDraw

from pws import theme
from pws.core.layer import Layer

#: Rows that get a coloured accent, keyed by label.
_ACCENTS = {
    "Sunrise": theme.AMBER,
    "Sunset": theme.ROSE,
    "Dawn": theme.AMBER,
    "Dusk": theme.ROSE,
    "Moon Phase": theme.VIOLET,
    "UV Index": theme.AMBER,
    "Dew Point": theme.CYAN,
    "Humidity": theme.CYAN,
    "Cloud Cover": theme.CLOUD,
    "Rain Today": theme.PRECIP,
    "Snow Today": theme.CYAN,
    "Ice Today": theme.CYAN,
    "Fire Index": theme.ROSE,
    "Smoke": theme.CLOUD,
    "Nearest Storm": theme.PRECIP,
}


class AlmanacLayer(Layer):
    """Two-column grid of labelled almanac values."""

    name = "almanac"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_rows: Callable[[], List[Dict[str, Any]]],
        min_interval: float = 20.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_rows = get_rows

    def tick(self, now: float):
        try:
            rows = self.get_rows() or []
        except Exception:
            rows = []

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

        if not rows:
            draw.text((self.s(32), self.s(28)), "Almanac data unavailable",
                      font=theme.font(self.s(34, 12), "medium"), fill=theme.TEXT_MUTED)
            return self._mark_all_dirty_if_changed()

        pad = self.s(34)
        cols = 2
        gap = self.s(22, 1)
        col_w = (w - pad * 2 - gap * (cols - 1)) // cols

        label_font = theme.font(self.s(21, 9), "semibold")
        value_font = theme.font(self.s(34, 12), "bold")

        # Fit as many rows as will sit at a comfortable minimum height, then
        # divide the space evenly so the grid fills the card rather than
        # leaving a gap along the bottom.
        available = h - pad * 2
        min_row_h = self.s(74, 1)
        per_col = max(1, available // min_row_h)
        rows = rows[: per_col * cols]
        per_col = max(1, min(per_col, -(-len(rows) // cols)))
        row_h = max(min_row_h, available // per_col)
        stripe_inset = self.s(5, 1)

        for index, row in enumerate(rows):
            col = index // per_col
            slot = index % per_col
            if col >= cols:
                break
            x0 = pad + col * (col_w + gap)
            y0 = pad + slot * row_h
            centre = y0 + row_h / 2.0

            name = str(row.get("name") or "")
            value = str(row.get("value") or "--")
            accent = _ACCENTS.get(name, theme.ACCENT)

            # Zebra striping for scannability.
            if slot % 2 == 0:
                theme.card(
                    surface,
                    (x0, y0 + stripe_inset, x0 + col_w, y0 + row_h - stripe_inset),
                    radius=self.s(12, 1),
                    fill=theme.with_alpha(theme.TEXT, 8),
                    border=None, shadow=False, top_highlight=False,
                )
                draw = ImageDraw.Draw(surface, "RGBA")

            # Accent bar, label and value all share one centre line, so the
            # differing font sizes no longer read as two separate rows.
            bar_h = max(self.s(20, 1), row_h - self.s(34))
            bar_x = x0 + self.s(14)
            theme.accent_rule(draw, bar_x, int(centre - bar_h / 2), self.s(4),
                              bar_h, color=accent)

            text_x = bar_x + self.s(18)
            theme.label(draw, (text_x, theme.top_for_center(label_font, centre)),
                        name, label_font, fill=theme.TEXT_DIM,
                        tracking=self.s(2, 1))
            theme.text_right(
                draw,
                (x0 + col_w - self.s(18), theme.top_for_center(value_font, centre)),
                value, value_font, fill=theme.TEXT,
            )

        return self._mark_all_dirty_if_changed()
