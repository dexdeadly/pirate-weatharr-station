"""Header column 3: the current temperature, always on screen."""
from __future__ import annotations

from typing import Any, Callable, Dict

from PIL import ImageDraw

from pws import layout, theme
from pws.core.layer import Layer
from pws.layers.anim_icons import AnimatedIconsMixin


class HeaderCurrentLayer(AnimatedIconsMixin, Layer):
    """
    Persistent "currently" readout in the header band.

    This used to be a small pill tucked under the clock, which floated over the
    alert banner and was hard to read at a glance. It now occupies its own
    header column, aligned to the same label/body baselines as the other three.
    """

    name = "header_current"

    def __init__(
        self,
        *,
        x: int,
        y: int,
        w: int,
        h: int,
        get_data: Callable[[], Dict[str, Any]],
        min_interval: float = 5.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_data = get_data
        self._init_icons()
        self.min_interval = self._icon_interval()

    def tick(self, now: float):
        try:
            data = self.get_data() or {}
        except Exception:
            data = {}

        temp = str(data.get("temp_display") or "--°")
        unit = str(data.get("temp_unit") or "F")
        summary = str(data.get("summary") or "")
        feels = str(data.get("feels_display") or "")
        icon_key = str(data.get("icon") or "clear-day")
        temp_f = data.get("temp_f")

        state = (temp, unit, summary, feels, icon_key)

        def draw_static() -> None:
            self._paint(temp, unit, summary, feels, icon_key, temp_f)

        return self._render_with_icons(now, state, draw_static)

    def _paint(self, temp: str, unit: str, summary: str, feels: str,
               icon_key: str, temp_f) -> None:
        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        draw = ImageDraw.Draw(surface, "RGBA")

        w = self.surface.width
        cx = w // 2

        # Column label, on the shared baseline.
        label_font = theme.font(self.s(18, 8), "semibold")
        theme.tracked_center(draw, cx, self.s(layout.LABEL_Y) - self.bounds[1],
                             "CURRENTLY", label_font, fill=theme.TEXT_DIM,
                             tracking=self.s(3, 1))

        body_y = self.s(layout.BODY_Y) - self.bounds[1]
        color = theme.temp_color(temp_f)

        # Measure the icon + temperature + unit row, then centre it as a group.
        icon_size = self.s(62, 1)
        temp_font = theme.font(self.s(62, 17), "black")
        unit_font = theme.font(self.s(26, 10), "bold")
        temp_w = theme.text_width(draw, temp, temp_font)
        unit_w = theme.text_width(draw, unit, unit_font)

        row_w = temp_w + self.s(4) + unit_w + icon_size + self.s(12)

        x = max(0, cx - row_w // 2)
        self._register_icon(x, body_y, icon_size, icon_key)
        x += icon_size + self.s(12)

        draw.text((x, body_y - self.s(4)), temp, font=temp_font, fill=color)
        draw.text((x + temp_w + self.s(4), body_y + self.s(6)), unit,
                  font=unit_font, fill=theme.with_alpha(color, 210))

        # Condition + feels-like on one muted line beneath, also centred.
        detail_font = theme.font(self.s(20, 8), "medium")
        detail = summary
        if feels and feels not in ("--°F", "--°C"):
            detail = f"{summary} · Feels {feels}" if summary else f"Feels {feels}"
        detail_y = body_y + theme.line_height(temp_font) - self.s(6)
        lines = theme.wrap(draw, detail, detail_font, w, max_lines=1)
        if lines:
            theme.tracked_center(draw, cx, detail_y, lines[0].upper(), detail_font,
                                 fill=theme.TEXT_MUTED, tracking=self.s(1, 1))
