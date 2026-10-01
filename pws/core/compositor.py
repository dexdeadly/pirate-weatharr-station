# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/core/compositor.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations
from typing import Iterable, List, Optional, Tuple
from PIL import Image

Rect = Tuple[int, int, int, int]  # x, y, w, h (screen coordinates)


def _intersect(a: Rect, b: Rect) -> Optional[Rect]:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


class Compositor:
    """
    Single frame buffer, repainted only where layers changed.

    The original rebuilt the entire frame from every visible layer whenever
    anything changed - and the ticker changes every frame, so that was a full
    1080p alpha composite every frame just to scroll a 64px strip.
    """

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.frame = Image.new("RGBA", (w, h), (0, 0, 0, 255))
        self._bytes: bytes | None = None

    def compose(self, layers: List["Layer"], dirty: Optional[Iterable[Rect]] = None) -> None:
        """Repaint the dirty screen rects (whole frame when None) from visible layers, bottom-up."""
        screen = (0, 0, self.w, self.h)
        if dirty is None:
            rects = [screen]
        else:
            rects = [r for r in (_intersect(d, screen) for d in dirty) if r]
        for rx, ry, rw, rh in rects:
            self.frame.paste((0, 0, 0, 255), (rx, ry, rx + rw, ry + rh))
            for layer in layers:
                if not getattr(layer, "visible", True):
                    continue
                lx, ly, lw, lh = layer.bounds
                if lw <= 0 or lh <= 0:
                    continue
                hit = _intersect((rx, ry, rw, rh), (lx, ly, lw, lh))
                if hit is None:
                    continue
                x, y, w, h = hit
                sx, sy = x - lx, y - ly
                self.frame.alpha_composite(layer.surface, dest=(x, y),
                                           source=(sx, sy, sx + w, sy + h))
        if rects:
            self._bytes = None

    def frame_bytes(self) -> bytes:
        """Raw RGBA bytes of the current frame, reused until the next compose changes it."""
        if self._bytes is None:
            self._bytes = self.frame.tobytes()
        return self._bytes
