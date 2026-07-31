"""Animated radar layer (RainViewer tiles composited over an OSM base map)."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/radar.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from collections import deque
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageDraw

from pws import theme
from pws.core.layer import Layer


class RadarLayer(Layer):
    """
    Cheap radar animation.

    Frames are pre-scaled once on ingest, then cycled with a hold counter so the
    loop plays slower than the layer's tick rate. Radar imagery comes from
    RainViewer rather than the weather provider, so it is unaffected by the
    switch to Pirate Weather.

    Modernised styling: rounded corner mask, hairline border, a timestamp chip
    and a dBZ intensity legend.
    """

    name = "radar"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        min_interval: float = 0.1,
        get_new_frames: Optional[Callable[[], List[Tuple[Image.Image, str]]]] = None,
        frame_hold: int = 3,
        get_source: Optional[Callable[[], str]] = None,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.frames: deque[Image.Image] = deque(maxlen=12)
        self.labels: deque[str] = deque(maxlen=12)
        self.idx = 0
        self.get_new_frames = get_new_frames
        self.frame_hold = max(1, int(frame_hold))
        self.get_source = get_source
        self._hold = 0
        self._mask: Image.Image | None = None

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

    def ingest_frame(self, img: Image.Image, label: str | None = "") -> None:
        if img is None:
            return
        try:
            scaled = img.convert("RGBA").resize(
                (self.bounds[2], self.bounds[3]), Image.BILINEAR
            )
            self.frames.append(scaled)
            self.labels.append(label or "")
        except Exception:
            pass

    # -- render -----------------------------------------------------------

    def tick(self, now: float):
        if self.get_new_frames:
            try:
                for item in self.get_new_frames() or []:
                    if isinstance(item, tuple) and item:
                        self.ingest_frame(item[0], item[1] if len(item) > 1 else "")
                    else:
                        self.ingest_frame(item, "")
            except Exception:
                pass

        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))

        if not self.frames:
            theme.card(surface, (0, 0, surface.width, surface.height),
                       radius=self.s(theme.RADIUS_CARD, 1))
            draw = ImageDraw.Draw(surface, "RGBA")
            draw.text((self.s(32), self.s(28)), "Acquiring radar imagery…",
                      font=theme.font(self.s(34, 12), "medium"), fill=theme.TEXT_MUTED)
            return self._mark_all_dirty_if_changed()

        frame = self.frames[self.idx % len(self.frames)]
        surface.paste(frame, (0, 0), self._corner_mask())

        draw = ImageDraw.Draw(surface, "RGBA")
        draw.rounded_rectangle(
            (0, 0, surface.width - 1, surface.height - 1),
            radius=theme.radius_of(self.s(theme.RADIUS_CARD)),
            outline=theme.CARD_BORDER_STRONG, width=self.s(2, 1),
        )

        # Timestamp chip (top-left)
        label = self.labels[self.idx % len(self.labels)] if self.labels else ""
        if label:
            font = theme.font(self.s(24, 10), "bold")
            tw = theme.text_width(draw, label, font)
            th = theme.line_height(font)
            x, y = self.s(20), self.s(20)
            theme.pill(draw, (x, y, x + tw + self.s(32), y + th + self.s(14)),
                       fill=(8, 12, 24, 200),
                       border=theme.with_alpha(theme.ACCENT, 130),
                       border_width=self.s(2, 1))
            draw.text((x + self.s(16), y + self.s(7)), label, font=font, fill=theme.TEXT)

        self._draw_legend(draw)
        self._draw_source_badge(draw)

        self._hold += 1
        if self._hold >= self.frame_hold:
            self._hold = 0
            self.idx += 1
        return self._mark_all_dirty_if_changed()

    def _draw_legend(self, draw) -> None:
        """Reflectivity ramp in the bottom-right corner."""
        stops = [
            (0, 236, 236), (0, 160, 246), (0, 255, 0), (0, 200, 0),
            (0, 144, 0), (255, 255, 0), (231, 192, 0), (255, 144, 0),
            (255, 0, 0), (214, 0, 0), (255, 0, 255),
        ]
        font = theme.font(self.s(17, 8), "semibold")
        bar_w = self.s(20, 3)
        bar_h = self.s(14, 3)
        total_w = bar_w * len(stops)
        x0 = self.s(24)
        x1 = x0 + total_w
        y1 = self.surface.height - self.s(24)
        y0 = y1 - bar_h

        theme.pill(draw,
                   (x0 - self.s(14), y0 - self.s(24), x1 + self.s(14), y1 + self.s(10)),
                   fill=(8, 12, 24, 190))
        for i, color in enumerate(stops):
            draw.rectangle((x0 + i * bar_w, y0, x0 + (i + 1) * bar_w, y1),
                           fill=(*color, 235))
        theme.label(draw, (x0, y0 - self.s(20)), "Light", font,
                    fill=theme.TEXT_DIM, tracking=self.s(1, 1))
        theme.text_right(draw, (x1, y0 - self.s(20)), "HEAVY", font, fill=theme.TEXT_DIM)

    def _draw_source_badge(self, draw) -> None:
        """
        Imagery credit, bottom-right.

        Reflects the source that actually supplied the frames, so the credit
        stays truthful when the feed falls back from NOAA to RainViewer.
        """
        source = ""
        if callable(self.get_source):
            try:
                source = str(self.get_source() or "").strip()
            except Exception:
                source = ""
        if not source:
            return

        label_font = theme.font(self.s(16, 7), "semibold")
        name_font = theme.font(self.s(21, 9), "bold")
        pad = self.s(12, 2)

        label_w = theme.tracked_width(draw, "RADAR", label_font, self.s(2, 1))
        name_w = theme.text_width(draw, source, name_font)
        box_w = pad * 2 + max(label_w, name_w)
        box_h = pad * 2 + theme.line_height(label_font) + theme.line_height(name_font)

        x1 = self.surface.width - self.s(24)
        y1 = self.surface.height - self.s(24)
        x0, y0 = x1 - box_w, y1 - box_h

        draw.rectangle((x0, y0, x1, y1), fill=(8, 12, 24, 200),
                       outline=theme.with_alpha(theme.CARD_BORDER_STRONG, 150),
                       width=self.s(2, 1))
        theme.tracked_text(draw, (x0 + pad, y0 + pad), "RADAR", label_font,
                           fill=theme.TEXT_DIM, tracking=self.s(2, 1))
        draw.text((x0 + pad, y0 + pad + theme.line_height(label_font)), source,
                  font=name_font, fill=theme.TEXT)
