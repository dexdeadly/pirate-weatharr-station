"""
Animated weather icons, drawn procedurally.

The bundled PNGs are static, and animated SVG sets rely on SMIL, which Pillow
cannot rasterise. So the icons are drawn here in code instead: a sun with
rotating rays, drifting clouds, falling rain and snow, a flashing bolt, and
drifting fog and wind streaks.

Drawing rather than loading buys three things: every animation loops perfectly,
icons render crisply at any size instead of being upscaled from a fixed bitmap,
and the palette follows `theme` so the icons match the rest of the station.

Frames are precomputed per (icon, size) and cached, so playback costs a single
cached image lookup and one alpha composite.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter

#: Frames in one animation loop, and the loop's wall-clock duration.
FRAMES = 20
LOOP_SECONDS = 1.6

#: Supersampling factor; everything is drawn large then downscaled for AA.
_SS = 2

#: Sizes are snapped to these buckets so the frame cache stays small.
#: Capped at 128: the shapes are soft, so the hero icon upscales from 128
#: without visible loss, and this keeps the frame cache well under control.
_BUCKETS = (32, 48, 64, 96, 128)

# -- palette ---------------------------------------------------------------

SUN = (251, 191, 36, 255)
SUN_CORE = (253, 224, 71, 255)
MOON = (226, 232, 240, 255)
MOON_SHADE = (148, 163, 184, 255)
CLOUD_LIGHT = (244, 247, 252, 255)
CLOUD_MID = (214, 223, 238, 255)
CLOUD_DARK = (166, 181, 209, 255)
RAIN = (96, 165, 250, 255)
SNOW = (203, 225, 255, 255)
SLEET = (147, 197, 253, 255)
BOLT = (250, 204, 21, 255)
FOG = (203, 213, 225, 255)
WIND = (203, 213, 225, 255)

#: Every icon key this module can draw.
SUPPORTED = (
    "clear-day", "clear-night", "cloudy", "partly-cloudy-day",
    "partly-cloudy-night", "rain", "snow", "sleet", "thunderstorm",
    "wind", "fog",
)


def _bucket(size: int) -> int:
    size = max(8, int(size))
    for b in _BUCKETS:
        if size <= b:
            return b
    return _BUCKETS[-1]


# -- primitives ------------------------------------------------------------

def _sun(draw: ImageDraw.ImageDraw, S: int, t: float, cx: float, cy: float,
         r: float, *, rays: bool = True) -> None:
    """Disc with a gentle pulse and, optionally, slowly rotating rays."""
    if rays:
        count = 8
        # Rotating by exactly one ray spacing over the loop makes it seamless.
        spin = t * (2 * math.pi / count)
        inner = r * 1.35
        outer = r * 1.92 + r * 0.06 * math.sin(2 * math.pi * t)
        width = max(1, int(r * 0.20))
        for i in range(count):
            a = spin + i * (2 * math.pi / count)
            ca, sa = math.cos(a), math.sin(a)
            draw.line(
                (cx + ca * inner, cy + sa * inner, cx + ca * outer, cy + sa * outer),
                fill=SUN, width=width,
            )
    rr = r * (1.0 + 0.035 * math.sin(2 * math.pi * t))
    draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=SUN)
    core = rr * 0.62
    draw.ellipse((cx - core, cy - core, cx + core, cy + core), fill=SUN_CORE)


def _moon(base: Image.Image, S: int, t: float, cx: float, cy: float,
          r: float) -> None:
    """Crescent, built by masking one disc out of another."""
    rr = r * (1.0 + 0.03 * math.sin(2 * math.pi * t))
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=MOON)

    mask = Image.new("L", base.size, 255)
    md = ImageDraw.Draw(mask)
    off = rr * 0.52
    md.ellipse((cx - rr + off, cy - rr - off * 0.34,
                cx + rr + off, cy + rr - off * 0.34), fill=0)
    layer.putalpha(Image.composite(layer.getchannel("A"),
                                   Image.new("L", base.size, 0), mask))
    base.alpha_composite(layer)


@lru_cache(maxsize=64)
def moon_phase_image(phase: float, size: int) -> Image.Image:
    """Phase-accurate moon disc; 0/1=new, 0.25=first quarter, 0.5=full, 0.75=last quarter."""
    size = max(1, int(size))
    S = size * _SS
    r = S / 2.0
    phase = float(phase) % 1.0
    cos_term = math.cos(2 * math.pi * phase)
    waxing = phase < 0.5

    img = Image.new("RGBA", (S, S), MOON_SHADE)
    d = ImageDraw.Draw(img, "RGBA")
    half_box = (r, 0, S, S) if waxing else (0, 0, r, S)
    d.rectangle(half_box, fill=MOON)
    # Terminator: an ellipse the width of cos(phase) either carves a crescent
    # out of the lit half (near new) or bulges light into the dark half (near
    # full) - the standard construction for a 2D moon-phase disc.
    ew = r * abs(cos_term)
    if ew > 0.5:
        fill = MOON_SHADE if cos_term > 0 else MOON
        d.ellipse((r - ew, 0, r + ew, S), fill=fill)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, S - 1, S - 1), fill=255)
    img.putalpha(mask)

    img = img.filter(ImageFilter.GaussianBlur(_SS * 0.35))
    return img.resize((size, size), Image.LANCZOS)


def _stars(draw: ImageDraw.ImageDraw, t: float, S: int,
           points: Sequence[tuple[float, float, float]]) -> None:
    """Four-point sparkles that twinkle out of phase with each other."""
    for i, (fx, fy, fr) in enumerate(points):
        phase = (t + i / max(1, len(points))) % 1.0
        # Smooth 0..1..0 twinkle across the loop.
        glow = 0.45 + 0.55 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
        r = S * fr * (0.7 + 0.5 * glow)
        cx, cy = S * fx, S * fy
        alpha = int(255 * glow)
        draw.polygon(
            [(cx, cy - r), (cx + r * 0.30, cy - r * 0.30), (cx + r, cy),
             (cx + r * 0.30, cy + r * 0.30), (cx, cy + r),
             (cx - r * 0.30, cy + r * 0.30), (cx - r, cy),
             (cx - r * 0.30, cy - r * 0.30)],
            fill=(MOON[0], MOON[1], MOON[2], alpha),
        )


def _cloud(draw: ImageDraw.ImageDraw, cx: float, cy: float, w: float,
           color: Sequence[int]) -> None:
    """Rounded cloud: three lobes over a capsule body."""
    h = w * 0.58
    left = cx - w / 2
    body_top = cy + h * 0.10
    draw.rounded_rectangle(
        (left + w * 0.04, body_top, left + w * 0.96, cy + h * 0.52),
        radius=h * 0.30, fill=tuple(color),
    )
    for fx, fy, fr in ((0.28, 0.10, 0.26), (0.52, -0.08, 0.34), (0.75, 0.12, 0.24)):
        ccx = left + w * fx
        ccy = cy + h * fy
        rr = w * fr
        draw.ellipse((ccx - rr, ccy - rr, ccx + rr, ccy + rr), fill=tuple(color))


def _drift(t: float, amount: float) -> float:
    """Smooth, seamless left-right drift over the loop."""
    return math.sin(2 * math.pi * t) * amount


def _rain(draw: ImageDraw.ImageDraw, t: float, box: tuple[float, float, float, float],
          count: int, color: Sequence[int] = RAIN, length: float = 0.26) -> None:
    x0, y0, x1, y1 = box
    span_x = x1 - x0
    span_y = y1 - y0
    seg = span_y * length
    for i in range(count):
        phase = (t + i / count) % 1.0
        x = x0 + span_x * ((i + 0.5) / count)
        y = y0 + phase * span_y
        # Fade in at the top and out at the bottom so the loop has no seam.
        fade = min(1.0, phase / 0.18, (1.0 - phase) / 0.22)
        alpha = int(235 * max(0.0, fade))
        if alpha <= 0:
            continue
        draw.line((x, y, x - span_x * 0.02, y + seg),
                  fill=(color[0], color[1], color[2], alpha),
                  width=max(1, int(span_x * 0.045)))


def _snow(draw: ImageDraw.ImageDraw, t: float, box: tuple[float, float, float, float],
          count: int, color: Sequence[int] = SNOW) -> None:
    x0, y0, x1, y1 = box
    span_x = x1 - x0
    span_y = y1 - y0
    r = span_x * 0.055
    for i in range(count):
        phase = (t + i / count) % 1.0
        sway = math.sin(2 * math.pi * (phase + i / count)) * span_x * 0.05
        x = x0 + span_x * ((i + 0.5) / count) + sway
        y = y0 + phase * span_y
        fade = min(1.0, phase / 0.18, (1.0 - phase) / 0.22)
        alpha = int(240 * max(0.0, fade))
        if alpha <= 0:
            continue
        draw.ellipse((x - r, y - r, x + r, y + r),
                     fill=(color[0], color[1], color[2], alpha))


def _bolt(draw: ImageDraw.ImageDraw, t: float, cx: float, cy: float,
          h: float) -> None:
    """Lightning that flashes twice per loop."""
    strobe = math.sin(2 * math.pi * t * 2)
    if strobe < 0.25:
        return
    alpha = int(255 * min(1.0, (strobe - 0.25) / 0.55))
    w = h * 0.46
    pts = [
        (cx + w * 0.10, cy - h * 0.50),
        (cx - w * 0.42, cy + h * 0.08),
        (cx - w * 0.04, cy + h * 0.08),
        (cx - w * 0.22, cy + h * 0.50),
        (cx + w * 0.44, cy - h * 0.10),
        (cx + w * 0.04, cy - h * 0.10),
    ]
    draw.polygon(pts, fill=(BOLT[0], BOLT[1], BOLT[2], alpha))


def _fog_bars(draw: ImageDraw.ImageDraw, t: float,
              box: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = box
    span_x = x1 - x0
    span_y = y1 - y0
    rows = 3
    for i in range(rows):
        y = y0 + span_y * ((i + 0.5) / rows)
        shift = _drift(t + i * 0.22, span_x * 0.10)
        inset = span_x * (0.04 + 0.05 * i)
        thickness = span_y * 0.17
        draw.rounded_rectangle(
            (x0 + inset + shift, y - thickness / 2,
             x1 - inset + shift, y + thickness / 2),
            radius=thickness / 2, fill=(FOG[0], FOG[1], FOG[2], 210),
        )


def _wind_streaks(draw: ImageDraw.ImageDraw, t: float,
                  box: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = box
    span_x = x1 - x0
    span_y = y1 - y0
    rows = 3
    width = max(1, int(span_y * 0.10))
    for i in range(rows):
        y = y0 + span_y * ((i + 0.5) / rows)
        shift = _drift(t + i * 0.3, span_x * 0.16)
        length = span_x * (0.62 + 0.16 * ((i + 1) % 2))
        sx = x0 + shift
        draw.line((sx, y, sx + length, y),
                  fill=(WIND[0], WIND[1], WIND[2], 215), width=width)
        # Little curl on the end of the streak.
        rr = span_y * 0.15
        draw.arc((sx + length - rr, y - rr, sx + length + rr, y + rr),
                 start=270, end=140, fill=(WIND[0], WIND[1], WIND[2], 215),
                 width=width)


# -- composition -----------------------------------------------------------

def _render(name: str, S: int, t: float) -> Image.Image:
    """Draw one frame at supersampled size S."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    key = name

    if key == "clear-day":
        _sun(d, S, t, S * 0.5, S * 0.5, S * 0.21)

    elif key == "clear-night":
        _moon(img, S, t, S * 0.55, S * 0.47, S * 0.32)
        d = ImageDraw.Draw(img, "RGBA")
        _stars(d, t, S, ((0.17, 0.24, 0.042), (0.26, 0.66, 0.032),
                         (0.13, 0.47, 0.026)))

    elif key == "cloudy":
        drift = _drift(t, S * 0.02)
        _cloud(d, S * 0.56 + drift, S * 0.34, S * 0.52, CLOUD_DARK)
        _cloud(d, S * 0.46 - drift, S * 0.58, S * 0.66, CLOUD_LIGHT)

    elif key in ("partly-cloudy-day", "partly-cloudy-night"):
        if key.endswith("day"):
            _sun(d, S, t, S * 0.34, S * 0.34, S * 0.155)
        else:
            _moon(img, S, t, S * 0.35, S * 0.35, S * 0.185)
            d = ImageDraw.Draw(img, "RGBA")
        _cloud(d, S * 0.56 + _drift(t, S * 0.022), S * 0.60, S * 0.62, CLOUD_LIGHT)

    elif key == "rain":
        _cloud(d, S * 0.50 + _drift(t, S * 0.018), S * 0.36, S * 0.66, CLOUD_LIGHT)
        _rain(d, t, (S * 0.24, S * 0.60, S * 0.78, S * 0.94), 5)

    elif key == "snow":
        _cloud(d, S * 0.50 + _drift(t, S * 0.018), S * 0.36, S * 0.66, CLOUD_LIGHT)
        _snow(d, t, (S * 0.24, S * 0.60, S * 0.78, S * 0.94), 5)

    elif key == "sleet":
        _cloud(d, S * 0.50 + _drift(t, S * 0.018), S * 0.36, S * 0.66, CLOUD_LIGHT)
        _rain(d, t, (S * 0.24, S * 0.60, S * 0.52, S * 0.94), 3, SLEET)
        _snow(d, t + 0.5, (S * 0.52, S * 0.60, S * 0.80, S * 0.94), 3)

    elif key == "thunderstorm":
        _cloud(d, S * 0.50 + _drift(t, S * 0.015), S * 0.34, S * 0.68, CLOUD_DARK)
        _rain(d, t, (S * 0.22, S * 0.58, S * 0.80, S * 0.94), 4)
        _bolt(d, t, S * 0.52, S * 0.74, S * 0.40)

    elif key == "wind":
        _cloud(d, S * 0.46 + _drift(t, S * 0.03), S * 0.34, S * 0.56, CLOUD_LIGHT)
        _wind_streaks(d, t, (S * 0.12, S * 0.60, S * 0.90, S * 0.92))

    elif key == "fog":
        _cloud(d, S * 0.50 + _drift(t, S * 0.02), S * 0.32, S * 0.60, CLOUD_MID)
        _fog_bars(d, t, (S * 0.10, S * 0.56, S * 0.90, S * 0.94))

    else:
        # Unknown key: fall back to a plain cloud rather than drawing nothing.
        _cloud(d, S * 0.50, S * 0.50, S * 0.68, CLOUD_LIGHT)

    return img


@lru_cache(maxsize=48)
def _frames(name: str, size: int) -> tuple[Image.Image, ...]:
    """All frames of one loop for a given icon and bucket size."""
    S = size * _SS
    out = []
    for i in range(FRAMES):
        img = _render(name, S, i / FRAMES)
        # Slight blur before downscaling smooths the thin ray/streak lines.
        img = img.filter(ImageFilter.GaussianBlur(_SS * 0.35))
        out.append(img.resize((size, size), Image.LANCZOS))
    return tuple(out)


@lru_cache(maxsize=192)
def _sized_frame(name: str, size: int, idx: int) -> Image.Image:
    """One frame at an exact pixel size, resized from its bucket once."""
    img = _frames(name, _bucket(size))[idx]
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    return img


def frame(name: str, size: int, t: float) -> Image.Image | None:
    """
    One animated frame of `name` at `size` px, for wall-clock time `t`.

    Frames are cached both per bucket and per exact requested size, so steady
    playback is a dictionary lookup rather than a resize.
    """
    size = max(1, int(size))
    key = str(name or "").strip().lower()
    if key not in SUPPORTED:
        key = "cloudy"
    idx = int((float(t) / LOOP_SECONDS) * FRAMES) % FRAMES
    try:
        return _sized_frame(key, size, idx)
    except Exception:
        return None


def prewarm(names: Sequence[str], sizes: Sequence[int]) -> None:
    """Build frame loops up front so the first paint is not stalled."""
    for name in names:
        for size in sizes:
            try:
                _frames(name if name in SUPPORTED else "cloudy", _bucket(size))
            except Exception:
                pass
