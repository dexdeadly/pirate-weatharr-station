"""
Animated-icon support for page layers.

Repainting a whole page layer at animation speed would be far too expensive -
the cards use blurred drop shadows and a lot of text. Instead a layer draws
itself once, without its icons, and keeps that as a background snapshot. On
every subsequent frame it restores just the icon rectangles from the snapshot
and composites the current animation frame over them.

That turns per-frame cost from "redraw a 1824x732 panel" into "a handful of
small crops and composites", and lets the layer report only those rectangles as
dirty.
"""
from __future__ import annotations

import time
from typing import Callable, List, Tuple

from PIL import Image

from pws import icons_anim

DirtyRect = Tuple[int, int, int, int]


class AnimatedIconsMixin:
    """
    Mix in alongside `Layer`.

    A subclass draws its static content in `_draw_static()`, calling
    `_register_icon(x, y, size, key)` wherever an icon belongs instead of
    drawing one. The mixin handles caching, animation and dirty rects.
    """

    #: Animation cadence. One loop is icons_anim.LOOP_SECONDS long.
    icon_fps: float = 12.5

    def _init_icons(self) -> None:
        self._icon_slots: list[tuple[int, int, int, str]] = []
        self._icon_bg: Image.Image | None = None
        self._icon_state: object = None
        self._collecting = False

    # -- called from subclasses -------------------------------------------

    def _register_icon(self, x: int, y: int, size: int, key: str) -> None:
        """Reserve an icon rectangle during the static draw."""
        size = max(1, int(size))
        self._icon_slots.append((int(x), int(y), size, str(key or "cloudy")))

    # -- driving ------------------------------------------------------------

    def _animate_icons(self, now: float) -> List[DirtyRect]:
        """Restore each icon rect from the background and composite a frame."""
        bg = self._icon_bg
        if bg is None or not self._icon_slots:
            return []
        surface = self.surface
        rects: List[DirtyRect] = []
        for x, y, size, key in self._icon_slots:
            box = (x, y, x + size, y + size)
            if box[0] < 0 or box[1] < 0 or box[2] > surface.width \
                    or box[3] > surface.height:
                continue
            surface.paste(bg.crop(box), (x, y))
            img = icons_anim.frame(key, size, now)
            if img is not None:
                surface.alpha_composite(img, dest=(x, y))
            rects.append((x, y, size, size))
        return rects

    def _render_with_icons(self, now: float, state: object,
                           draw_static: Callable[[], None]) -> List[DirtyRect]:
        """
        Entry point for a subclass `tick`.

        `state` is any hashable snapshot of the layer's inputs; when it changes
        the static content is redrawn and the background snapshot refreshed.
        """
        if not getattr(self, "visible", True):
            return []

        if state != self._icon_state or self._icon_bg is None:
            self._icon_state = state
            self._icon_slots = []
            draw_static()
            # Snapshot after the static pass, with icon areas still empty.
            self._icon_bg = self.surface.copy()
            self._animate_icons(now)
            w, h = self.surface.size
            return [(0, 0, w, h)]

        return self._animate_icons(now)

    def _icon_interval(self) -> float:
        return max(0.02, 1.0 / max(1.0, float(self.icon_fps)))
