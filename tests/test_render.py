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


def test_page_cycler_takes_turns_between_locations():
    from pws.main import PageCycler
    current, maps = Box(0, 0, 10, 10, (1, 1, 1, 255)), Box(0, 0, 10, 10, (2, 2, 2, 255))
    radar_a, radar_b = Box(0, 0, 10, 10, (3, 3, 3, 255)), Box(0, 0, 10, 10, (4, 4, 4, 255))
    header = Box(0, 0, 10, 10, (5, 5, 5, 255))
    pages = [
        {"name": "current", "layers": [current], "loc": 0},
        {"name": "radar", "layers": [radar_a], "loc": 0},
        {"name": "current", "layers": [current], "loc": 1},   # same layer, next location
        {"name": "radar", "layers": [radar_b], "loc": 1},     # per-location radar
        {"name": "regional", "layers": [maps], "loc": 1},
    ]
    switched = []
    cycler = PageCycler(pages, 10, on_location=switched.append, persistent=[header])

    cycler.activate(0)
    assert switched == [0] and current.visible and not radar_a.visible
    cycler.activate(1)
    assert switched == [0] and radar_a.visible and not current.visible
    gen_current, gen_header = current.generation, header.generation
    cycler.activate(2)                     # location changes on a shared layer
    assert switched == [0, 1]
    assert current.visible and not radar_a.visible and not radar_b.visible
    assert current.generation > gen_current and header.generation > gen_header
    cycler.activate(3)
    assert radar_b.visible and not radar_a.visible and not current.visible
    cycler.activate(5)                     # wraps to the first location again
    assert switched == [0, 1, 0] and current.visible
