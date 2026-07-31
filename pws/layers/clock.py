"""Header column 4: local time and date."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/clock.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from PIL import ImageDraw

from pws import layout, theme
from pws.core.layer import Layer
from pws.utils import now_local


class ClockLayer(Layer):
    """
    Time and date, centred in the last header column.

    Repaints only when a rendered string changes, so it costs one redraw per
    second rather than one per output frame. The current temperature used to
    live here as a pill; it now has its own column (see HeaderCurrentLayer).
    """

    name = "clock"

    def __init__(
        self,
        *,
        x: int,
        y: int,
        w: int,
        h: int,
        min_interval: float = 1.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self._state: tuple | None = None

    def tick(self, now: float):
        dt = now_local()
        time_str = dt.strftime("%I:%M").lstrip("0")
        secs_str = dt.strftime("%S")
        ampm = dt.strftime("%p")
        date_str = dt.strftime("%A, %B %d").replace(" 0", " ")

        state = (time_str, secs_str, ampm, date_str)
        if state == self._state:
            return []
        self._state = state

        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        draw = ImageDraw.Draw(surface, "RGBA")
        right = surface.width

        w = surface.width
        cx = w // 2

        # Column label, on the shared baseline.
        label_font = theme.font(self.s(18, 8), "semibold")
        theme.tracked_center(draw, cx, self.s(layout.LABEL_Y) - self.bounds[1],
                             "LOCAL TIME", label_font, fill=theme.TEXT_DIM,
                             tracking=self.s(3, 1))

        body_y = self.s(layout.BODY_Y) - self.bounds[1]
        time_font = theme.font(self.s(62, 17), "bold")
        small_font = theme.font(self.s(23, 9), "semibold")

        # Seconds and meridiem stack to the right of the big hours:minutes;
        # measure the pair, then centre the whole group in the column.
        stack_w = max(theme.text_width(draw, secs_str, small_font),
                      theme.text_width(draw, ampm, small_font))
        time_w = theme.text_width(draw, time_str, time_font)
        row_w = time_w + self.s(10) + stack_w
        x0 = max(0, cx - row_w // 2)

        draw.text((x0, body_y - self.s(4)), time_str, font=time_font, fill=theme.TEXT)
        sx = x0 + time_w + self.s(10)
        draw.text((sx, body_y + self.s(2)), ampm, font=small_font, fill=theme.ACCENT)
        draw.text((sx, body_y + self.s(30)), secs_str, font=small_font,
                  fill=theme.TEXT_DIM)

        date_font = theme.font(self.s(23, 9), "medium")
        date_y = body_y + theme.line_height(time_font) - self.s(6)
        theme.tracked_center(draw, cx, date_y, date_str.upper(), date_font,
                             fill=theme.TEXT_MUTED, tracking=self.s(1, 1))

        return self._mark_all_dirty_if_changed()
