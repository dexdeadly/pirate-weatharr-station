"""Bottom scrolling ticker with a category cap and soft edge fades."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/ticker.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from typing import Callable, Optional

from PIL import Image, ImageDraw

from pws import theme
from pws.core.layer import Layer


class TickerLayer(Layer):
    """
    Continuous horizontal scroller.

    The text strip is rendered once per content change and then blitted at a
    moving offset, so per-frame cost is two crops and a paste. A coloured cap on
    the left names the current feed ("ALERTS" / "NEWS"), and both ends fade into
    the tray instead of hard-clipping mid-glyph.
    """

    name = "ticker"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        min_interval: float,
        px_per_sec: int,
        get_text: Callable[[], str],
        *,
        get_label: Optional[Callable[[], str]] = None,
        get_accent: Optional[Callable[[], tuple]] = None,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.speed = float(px_per_sec)
        self.get_text = get_text
        self.get_label = get_label
        self.get_accent = get_accent
        self._font = theme.font(self.s(28, 11), "medium")
        self._label_font = theme.font(self.s(21, 9), "bold")
        self._strip: Image.Image | None = None
        self._offset = 0.0
        self._last_text = ""
        self._cap_w = 0
        self._fade: Image.Image | None = None

    # -- content ----------------------------------------------------------

    def _safe(self, fn, default):
        if not callable(fn):
            return default
        try:
            value = fn()
        except Exception:
            return default
        return value if value else default

    def _build_strip(self, text: str) -> None:
        spacer = "     •     "
        # Repeat enough times that the strip always exceeds the viewport.
        probe = Image.new("RGBA", (1, 1))
        pd = ImageDraw.Draw(probe)
        single_w = max(1, theme.text_width(pd, text + spacer, self._font))
        repeats = max(2, (self.bounds[2] * 2) // single_w + 2)
        long_text = (text + spacer) * repeats

        total_w = max(1, theme.text_width(pd, long_text, self._font))
        h = self.bounds[3]
        strip = Image.new("RGBA", (total_w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(strip)
        box = sd.textbbox((0, 0), long_text, font=self._font)
        y = max(0, (h - (box[3] - box[1])) // 2 - box[1])
        sd.text((-box[0], y), long_text, font=self._font, fill=theme.TEXT)
        self._strip = strip
        self._offset = 0.0

    def _build_fade(self, width: int, height: int) -> Image.Image:
        """Horizontal alpha mask that fades the first/last few pixels."""
        fade_w = max(3, self.s(24, 3))
        mask = Image.new("L", (width, 1), 255)
        px = mask.load()
        for i in range(min(fade_w, width)):
            value = int(255 * (i / fade_w))
            px[i, 0] = value
            px[width - 1 - i, 0] = value
        return mask.resize((width, height), Image.BILINEAR)

    # -- render -----------------------------------------------------------

    def tick(self, now: float):
        text = str(self._safe(self.get_text, "")).strip() or "Weather data loading…"
        if text != self._last_text or self._strip is None:
            self._last_text = text
            self._build_strip(text)

        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        draw = ImageDraw.Draw(surface, "RGBA")

        accent = self._safe(self.get_accent, theme.ACCENT)
        cap_text = str(self._safe(self.get_label, "WEATHER")).upper()

        # Left cap
        pad = self.s(18, 1)
        cap_text_w = theme.text_width(draw, cap_text, self._label_font) \
            + self.s(2, 1) * max(0, len(cap_text) - 1)
        cap_w = cap_text_w + pad * 2
        theme.pill(
            draw,
            (self.s(10, 1), self.s(8, 1), self.s(10, 1) + cap_w, surface.height - self.s(8, 1)),
            fill=tuple(accent),
        )
        cap_h = surface.height - self.s(16, 1)
        ty = self.s(8, 1) + max(0, (cap_h - theme.line_height(self._label_font)) // 2)
        theme.tracked_text(draw, (self.s(10, 1) + pad, ty), cap_text,
                           self._label_font, fill=theme.TEXT_ON_ACCENT,
                           tracking=self.s(2, 1))

        # Scrolling viewport to the right of the cap
        view_x = self.s(10, 1) + cap_w + self.s(18, 1)
        view_w = surface.width - view_x - self.s(10, 1)
        if view_w <= 0 or self._strip is None:
            return self._mark_all_dirty_if_changed()

        strip = self._strip
        h = min(surface.height, strip.height)
        window = Image.new("RGBA", (view_w, h), (0, 0, 0, 0))
        x0 = int(self._offset) % strip.width
        first = strip.crop((x0, 0, min(x0 + view_w, strip.width), h))
        window.paste(first, (0, 0))
        if first.width < view_w:
            second = strip.crop((0, 0, view_w - first.width, h))
            window.paste(second, (first.width, 0))

        if self._fade is None or self._fade.size != (view_w, h):
            self._fade = self._build_fade(view_w, h)
        window.putalpha(
            Image.composite(window.getchannel("A"), Image.new("L", (view_w, h), 0), self._fade)
        )
        surface.alpha_composite(window, dest=(view_x, 0))

        self._offset += self.speed * self.min_interval
        return self._mark_all_dirty_if_changed()
