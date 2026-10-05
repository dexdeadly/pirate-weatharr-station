"""Compositor dirty rects and scheduler frame pacing (simulated clock)."""
import random

from PIL import Image

from pws.core.compositor import Compositor
from pws.core.layer import Layer
from pws.core import scheduler as sched_mod


class Box(Layer):
    def __init__(self, x, y, w, h, color, interval=1.0, cost=0.0, clock=None):
        super().__init__(x, y, w, h, min_interval=interval)
        self.surface.paste(color, (0, 0, w, h))
        self.cost, self.clock, self.ticks = cost, clock, 0

    def tick(self, now):
        self.ticks += 1
        if self.clock:
            self.clock.t += self.cost
        w, h = self.surface.size
        return [(0, 0, w, h)]


def test_dirty_compose_matches_full_compose():
    rng = random.Random(1)
    layers = [Box(rng.randrange(0, 300), rng.randrange(0, 200), 120, 80,
                  (rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(80, 256)))
              for _ in range(8)]
    full, partial = Compositor(400, 300), Compositor(400, 300)
    full.compose(layers)
    partial.compose(layers)
    layers[3].surface.paste((255, 0, 0, 255), (0, 0, 120, 80))
    full.compose(layers)
    partial.compose(layers, [layers[3].bounds])
    assert full.frame.tobytes() == partial.frame.tobytes()


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


def run_scheduler(monkeypatch, seconds, fps, slow_every=None, slow_cost=0.3):
    clock = FakeClock()
    monkeypatch.setattr(sched_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(sched_mod.time, "sleep", clock.sleep)
    monkeypatch.setattr(sched_mod.time, "time", clock.monotonic)
    layers = [Box(0, 0, 50, 20, (0, 0, 0, 255), interval=1 / fps),
              Box(0, 30, 50, 20, (9, 9, 9, 255), interval=slow_every or 10**9,
                  cost=slow_cost if slow_every else 0, clock=clock)]
    start = clock.t
    frames = []
    s = sched_mod.Scheduler(layers, cfr_hz=fps)
    s.run_forever(Compositor(60, 60), on_present=lambda b: frames.append(clock.t),
                  should_stop=lambda: clock.t - start >= seconds)
    return len(frames), clock.t - start


def test_one_frame_per_period(monkeypatch):
    n, elapsed = run_scheduler(monkeypatch, 60, 30)
    # The first frame goes out at t=0, so N seconds holds N*fps + 1 frames.
    assert abs(n - (elapsed * 30 + 1)) < 1.5


def test_slow_ticks_do_not_lose_time(monkeypatch):
    # A 300 ms stall every 8 s (like building a new page) must not drop frames:
    # the frame count has to keep matching elapsed time at the target rate.
    n, elapsed = run_scheduler(monkeypatch, 120, 30, slow_every=8.0, slow_cost=0.3)
    assert abs(n - (elapsed * 30 + 1)) < 2.5
