# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/core/scheduler.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations
import time
from typing import Callable, List, Optional

from .layer import Layer
from .compositor import Compositor


class Scheduler:
    """
    Ticks visible layers on their own cadence and presents exactly one frame per
    output period.

    The original presented a frame whenever any layer was dirty *or* the CFR
    deadline passed, so the 30 Hz ticker alone pushed 30 frames/s into an
    ffmpeg told to expect ``cfr_hz``. At 24 fps that ran the stream clock ~1.3x
    faster than real time (45 s of wall clock became 63 s of video). Frames are
    now paced off a monotonic clock with ``next += period``, so the output rate
    matches ffmpeg's ``-r`` exactly and doesn't drift.
    """

    def __init__(self, layers: List[Layer], cfr_hz: int | None = 30):
        self.layers = sorted(layers, key=lambda L: getattr(L, "z", 0))
        self.cfr = max(1, int(cfr_hz or 30))
        self.period = 1.0 / self.cfr

    def run_forever(self, compositor: Compositor, on_present: Callable[[bytes], None],
                    should_stop: Optional[Callable[[], bool]] = None):
        clock = time.monotonic
        start = clock()
        due = [start] * len(self.layers)
        shown: list[Optional[bool]] = [None] * len(self.layers)
        next_frame = start
        while True:
            if should_stop and should_stop():
                break
            now = clock()
            if now < next_frame:
                time.sleep(next_frame - now)
                now = clock()
            elif now - next_frame > 5 * self.period:
                # Fell well behind (blocked output, slow page build): resync
                # rather than bursting a backlog of frames at ffmpeg.
                next_frame = now

            # Layers animate off wall-clock time, as before.
            wall = time.time()
            full = False
            dirty = []
            for i, L in enumerate(self.layers):
                visible = getattr(L, "visible", True)
                if visible != shown[i]:
                    shown[i] = visible
                    full = True
                    if visible:
                        # Hidden layers don't tick, so a page that just came
                        # on screen may be stale: draw it on this frame.
                        due[i] = now
                if not visible or now < due[i]:
                    continue
                rects = L.tick(wall)
                due[i] = now + L.min_interval
                lx, ly = L.bounds[0], L.bounds[1]
                dirty.extend((lx + x, ly + y, w, h) for x, y, w, h in rects)

            if full:
                compositor.compose(self.layers)
            elif dirty:
                compositor.compose(self.layers, dirty)
            on_present(compositor.frame_bytes())
            next_frame += self.period
