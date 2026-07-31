"""
Design system for the PWS broadcast surface.

Everything visual funnels through this module so the whole channel shares one
coherent look: a deep indigo gradient field, translucent "glass" cards with
hairline borders, a tight type scale in Inter, and a temperature-driven accent
ramp.

Layers should never hardcode colors or open font files directly - use the
helpers here so a single edit restyles the entire station.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RGBA = tuple[int, int, int, int]

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

# Background field (vertical gradient, top -> bottom)
BG_TOP: RGBA = (13, 18, 38, 255)
BG_BOTTOM: RGBA = (7, 10, 22, 255)

# Header / chrome
HEADER_TOP: RGBA = (24, 33, 66, 255)
HEADER_BOTTOM: RGBA = (14, 20, 43, 255)

# Glass surfaces
CARD_FILL: RGBA = (30, 41, 74, 214)
CARD_FILL_RAISED: RGBA = (38, 51, 90, 224)
CARD_FILL_SUNKEN: RGBA = (18, 25, 48, 214)
CARD_BORDER: RGBA = (128, 156, 214, 92)
CARD_BORDER_STRONG: RGBA = (150, 178, 235, 150)
SHADOW: RGBA = (0, 0, 0, 90)

# Text
TEXT: RGBA = (240, 245, 255, 255)
TEXT_MUTED: RGBA = (166, 181, 214, 255)
TEXT_DIM: RGBA = (124, 140, 176, 255)
TEXT_ON_ACCENT: RGBA = (8, 12, 24, 255)

# Accents
ACCENT: RGBA = (56, 189, 248, 255)          # sky-400, primary accent
ACCENT_SOFT: RGBA = (56, 189, 248, 44)
AMBER: RGBA = (251, 191, 36, 255)           # highs
CYAN: RGBA = (34, 211, 238, 255)
VIOLET: RGBA = (167, 139, 250, 255)
ROSE: RGBA = (251, 113, 133, 255)
LIME: RGBA = (163, 230, 53, 255)
PRECIP: RGBA = (96, 165, 250, 255)          # precipitation blue
CLOUD: RGBA = (203, 213, 225, 255)          # cloud cover grey
ALERT: RGBA = (248, 113, 113, 255)

# ---------------------------------------------------------------------------
# Style switches
# ---------------------------------------------------------------------------
# The station uses hard, square-cornered broadcast graphics. Rounded corners,
# blurred drop shadows and translucent top highlights were the soft
# "glassmorphism" idiom; they read as generic, so they are switched off here.
# Every radius in the codebase is funnelled through `radius()` below, so
# flipping SQUARE_CORNERS restores the rounded treatment everywhere at once.
SQUARE_CORNERS = True
SOFT_SHADOWS = False
BACKGROUND_GLOW = False
TOP_HIGHLIGHT = False

# Radii / metrics (design units at 1920x1080; scale via Layer.s())
RADIUS_CARD = 0
RADIUS_PILL = 0
HAIRLINE = 2


def radius_of(value: int) -> int:
    """Corner radius, forced to zero while SQUARE_CORNERS is set."""
    return 0 if SQUARE_CORNERS else max(0, int(value))

FONT_DIR_NAME = "fonts"

_WEIGHTS = {
    "regular": ("Inter-Regular.ttf",),
    "medium": ("Inter-Medium.ttf", "Inter-Regular.ttf"),
    "semibold": ("Inter-SemiBold.ttf", "Inter-Medium.ttf", "Inter-Regular.ttf"),
    "bold": ("Inter-Bold.ttf", "Inter-SemiBold.ttf", "Inter-Regular.ttf"),
    "black": ("Inter-Black.ttf", "Inter-Bold.ttf", "Inter-Regular.ttf"),
}

# System fallbacks if bundled assets are missing entirely.
_SYSTEM_FALLBACKS = {
    "regular": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",),
    "medium": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",),
    "semibold": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",),
    "bold": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",),
    "black": ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",),
}


# ---------------------------------------------------------------------------
# Asset resolution
# ---------------------------------------------------------------------------

def _asset_roots() -> list[Path]:
    """Candidate 'assets' directories, searching upward from this file."""
    here = Path(__file__).resolve()
    roots: list[Path] = []
    for parent in (here.parent, *here.parents):
        candidate = parent / "assets"
        if candidate.is_dir():
            roots.append(candidate)
        if len(roots) >= 3:
            break
    return roots


@lru_cache(maxsize=1)
def font_dir() -> Path | None:
    for root in _asset_roots():
        candidate = root / FONT_DIR_NAME
        if candidate.is_dir():
            return candidate
    return None


@lru_cache(maxsize=256)
def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """
    Resolve a font by logical weight, with graceful degradation.

    The original project loaded fonts via a relative path, which silently fell
    back to Pillow's bitmap default whenever the working directory differed -
    the single biggest cause of the old "dated" look. This resolver is absolute
    and cached.
    """
    size = max(8, int(size))
    names = _WEIGHTS.get(weight, _WEIGHTS["regular"])
    directory = font_dir()
    if directory:
        for name in names:
            path = directory / name
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size)
                except Exception:
                    continue
    for path_str in _SYSTEM_FALLBACKS.get(weight, ()):
        try:
            if Path(path_str).exists():
                return ImageFont.truetype(path_str, size)
        except Exception:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=64)
def icon_path(name: str) -> Path | None:
    """Locate assets/icons/<name>.png."""
    for root in _asset_roots():
        candidate = root / "icons" / f"{name}.png"
        if candidate.exists():
            return candidate
    return None


@lru_cache(maxsize=192)
def _icon_raw(path_str: str) -> Image.Image:
    return Image.open(path_str).convert("RGBA")


@lru_cache(maxsize=192)
def icon(name: str, size: int) -> Image.Image | None:
    """Load and cache a weather icon at an exact pixel size."""
    path = icon_path(name)
    if not path:
        return None
    size = max(1, int(size))
    try:
        base = _icon_raw(str(path))
    except Exception:
        return None
    if base.size != (size, size):
        base = base.resize((size, size), Image.LANCZOS)
    return base


@lru_cache(maxsize=1)
def logo_path() -> Path | None:
    """Locate the station logo bundled in assets/."""
    for root in _asset_roots():
        for name in ("logo.png", "logo.webp", "logo.jpg"):
            candidate = root / name
            if candidate.exists():
                return candidate
    return None


@lru_cache(maxsize=16)
def logo(height: int) -> Image.Image | None:
    """
    Station logo scaled to an exact height, aspect ratio preserved.

    Returns ``None`` when no logo is bundled, so callers can fall back to a
    text-only lockup rather than failing.
    """
    path = logo_path()
    if not path:
        return None
    height = max(1, int(height))
    try:
        base = Image.open(str(path)).convert("RGBA")
    except Exception:
        return None
    if base.height != height:
        width = max(1, int(round(base.width * (height / base.height))))
        base = base.resize((width, height), Image.LANCZOS)
    return base


# ---------------------------------------------------------------------------
# Color utilities
# ---------------------------------------------------------------------------

def with_alpha(color: Sequence[int], alpha: int) -> RGBA:
    r, g, b = color[0], color[1], color[2]
    return (int(r), int(g), int(b), max(0, min(255, int(alpha))))


def mix(a: Sequence[int], b: Sequence[int], t: float) -> RGBA:
    """Linear blend between two RGBA colors; t=0 -> a, t=1 -> b."""
    t = max(0.0, min(1.0, float(t)))
    out = []
    for i in range(4):
        av = a[i] if i < len(a) else 255
        bv = b[i] if i < len(b) else 255
        out.append(int(round(av + (bv - av) * t)))
    return (out[0], out[1], out[2], out[3])


# Temperature ramp stops in degrees Fahrenheit.
_TEMP_STOPS: list[tuple[float, RGBA]] = [
    (-10.0, (129, 140, 248, 255)),   # indigo
    (15.0, (96, 165, 250, 255)),     # blue
    (35.0, (34, 211, 238, 255)),     # cyan
    (52.0, (74, 222, 128, 255)),     # green
    (68.0, (250, 204, 21, 255)),     # yellow
    (82.0, (251, 146, 60, 255)),     # orange
    (95.0, (248, 113, 113, 255)),    # red
    (110.0, (232, 78, 155, 255)),    # magenta
]


def temp_color(value: float | int | None) -> RGBA:
    """Map a Fahrenheit temperature onto the accent ramp."""
    if value is None or not isinstance(value, (int, float)) or math.isnan(float(value)):
        return TEXT
    v = float(value)
    if v <= _TEMP_STOPS[0][0]:
        return _TEMP_STOPS[0][1]
    if v >= _TEMP_STOPS[-1][0]:
        return _TEMP_STOPS[-1][1]
    for (lo_v, lo_c), (hi_v, hi_c) in zip(_TEMP_STOPS, _TEMP_STOPS[1:]):
        if lo_v <= v <= hi_v:
            span = hi_v - lo_v or 1.0
            return mix(lo_c, hi_c, (v - lo_v) / span)
    return TEXT


def severity_color(severity: str | None) -> RGBA:
    key = (severity or "").strip().lower()
    return {
        "extreme": (244, 63, 94, 255),
        "severe": (248, 113, 113, 255),
        "moderate": (251, 146, 60, 255),
        "minor": (251, 191, 36, 255),
    }.get(key, ACCENT)


# ---------------------------------------------------------------------------
# Painting primitives
# ---------------------------------------------------------------------------

def vertical_gradient(size: tuple[int, int], top: Sequence[int], bottom: Sequence[int]) -> Image.Image:
    """Build a vertical gradient image cheaply (1px column, then resize)."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    strip = Image.new("RGBA", (1, h))
    px = strip.load()
    for y in range(h):
        px[0, y] = mix(top, bottom, y / max(1, h - 1))
    return strip.resize((w, h), Image.BILINEAR)


def paint_background(surface: Image.Image, *, top: Sequence[int] = BG_TOP,
                     bottom: Sequence[int] = BG_BOTTOM, glow: bool = True) -> None:
    """Fill a surface with the station's background field."""
    grad = vertical_gradient(surface.size, top, bottom)
    surface.paste(grad, (0, 0))
    if not glow or not BACKGROUND_GLOW:
        return
    # Soft radial accent glow in the upper-left for depth.
    w, h = surface.size
    radius = int(min(w, h) * 0.85)
    if radius < 8:
        return
    glow_img = Image.new("RGBA", (radius, radius), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_img)
    steps = 14
    for i in range(steps):
        t = i / steps
        inset = int(radius * 0.5 * t)
        alpha = int(16 * (1.0 - t))
        if alpha <= 0:
            continue
        gd.ellipse(
            (inset, inset, radius - inset, radius - inset),
            fill=with_alpha(ACCENT, alpha),
        )
    surface.alpha_composite(glow_img, dest=(-radius // 4, -radius // 3))


def rounded_shadow(surface: Image.Image, box: Sequence[int], radius: int,
                   *, spread: int = 10, alpha: int = 70) -> None:
    """Drop a soft shadow beneath a rounded rect (blurred alpha mask)."""
    if not SOFT_SHADOWS:
        return
    x0, y0, x1, y1 = (int(v) for v in box)
    spread = max(1, int(spread))
    pad = spread * 3
    w = (x1 - x0) + pad * 2
    h = (y1 - y0) + pad * 2
    if w <= 0 or h <= 0:
        return
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (pad, pad, pad + (x1 - x0), pad + (y1 - y0)),
        radius=radius_of(radius),
        fill=(0, 0, 0, max(0, min(255, int(alpha)))),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(spread))
    surface.alpha_composite(shadow, dest=(x0 - pad, y0 - pad + spread // 2))


def card(surface: Image.Image, box: Sequence[int], *, radius: int = RADIUS_CARD,
         fill: Sequence[int] = CARD_FILL, border: Sequence[int] | None = CARD_BORDER,
         border_width: int = HAIRLINE, shadow: bool = True, shadow_spread: int = 10,
         gradient_to: Sequence[int] | None = None, top_highlight: bool = True) -> None:
    """
    Draw a translucent "glass" panel: optional drop shadow, gradient body,
    hairline border, and a subtle top highlight that reads as a light source.
    """
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        return
    radius = radius_of(radius)

    if shadow and SOFT_SHADOWS:
        rounded_shadow(surface, (x0, y0, x1, y1), radius, spread=shadow_spread)

    w, h = x1 - x0, y1 - y0
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)

    if gradient_to is not None:
        body = vertical_gradient((w, h), fill, gradient_to)
    else:
        body = Image.new("RGBA", (w, h), tuple(fill))
    panel.paste(body, (0, 0), mask)

    pd = ImageDraw.Draw(panel)
    if top_highlight and TOP_HIGHLIGHT:
        # 1px inner highlight along the top edge.
        inset = radius // 2
        pd.line(
            (inset, 1, w - 1 - inset, 1),
            fill=(255, 255, 255, 26),
            width=max(1, border_width // 2),
        )
    if border is not None and border_width > 0:
        pd.rounded_rectangle(
            (0, 0, w - 1, h - 1),
            radius=radius,
            outline=tuple(border),
            width=max(1, int(border_width)),
        )

    surface.alpha_composite(panel, dest=(x0, y0))


def pill(draw: ImageDraw.ImageDraw, box: Sequence[int], *, fill: Sequence[int],
         border: Sequence[int] | None = None, border_width: int = 0) -> None:
    x0, y0, x1, y1 = (int(v) for v in box)
    radius = radius_of(max(1, (y1 - y0) // 2))
    draw.rounded_rectangle(
        (x0, y0, x1, y1),
        radius=radius,
        fill=tuple(fill),
        outline=tuple(border) if border else None,
        width=int(border_width),
    )


def accent_rule(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
                *, color: Sequence[int] = ACCENT) -> None:
    """The short accent bar used to the left of section titles."""
    draw.rounded_rectangle((x, y, x + max(1, w), y + max(1, h)),
                           radius=radius_of(max(1, w // 2)), fill=tuple(color))


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def text_width(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    if not text:
        return (0, 0)
    box = draw.textbbox((0, 0), text, font=fnt)
    return (box[2] - box[0], box[3] - box[1])


def tracked_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                 fnt: ImageFont.ImageFont, *, fill: Sequence[int] = TEXT,
                 tracking: int = 2) -> int:
    """
    Draw text with manual letter-spacing (Pillow has no tracking support).
    Used for the small uppercase labels that give the layout its editorial feel.
    Returns the total advance width.
    """
    x, y = int(xy[0]), int(xy[1])
    if not text:
        return 0
    start = x
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=tuple(fill))
        x += text_width(draw, ch, fnt) + int(tracking)
    return x - start - int(tracking)


def tracked_width(draw: ImageDraw.ImageDraw, text: str,
                  fnt: ImageFont.ImageFont, tracking: int = 2) -> int:
    """Advance width of `tracked_text` without drawing it."""
    if not text:
        return 0
    total = sum(text_width(draw, ch, fnt) for ch in text)
    return total + int(tracking) * max(0, len(text) - 1)


def tracked_center(draw: ImageDraw.ImageDraw, center_x: int, y: int, text: str,
                   fnt: ImageFont.ImageFont, *, fill: Sequence[int] = TEXT,
                   tracking: int = 2) -> int:
    """Centre tracked text horizontally on `center_x`."""
    w = tracked_width(draw, text, fnt, tracking)
    return tracked_text(draw, (int(center_x) - w // 2, y), text, fnt,
                        fill=fill, tracking=tracking)


def label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
          fnt: ImageFont.ImageFont, *, fill: Sequence[int] = TEXT_MUTED,
          tracking: int = 3) -> int:
    """Small caps-style metadata label."""
    return tracked_text(draw, xy, (text or "").upper(), fnt, fill=fill, tracking=tracking)


def text_right(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
               fnt: ImageFont.ImageFont, *, fill: Sequence[int] = TEXT) -> None:
    """Right-align text so its right edge lands on xy[0]."""
    w = text_width(draw, text, fnt)
    draw.text((int(xy[0]) - w, int(xy[1])), text, font=fnt, fill=tuple(fill))


def text_center(draw: ImageDraw.ImageDraw, center_x: int, y: int, text: str,
                fnt: ImageFont.ImageFont, *, fill: Sequence[int] = TEXT) -> None:
    w = text_width(draw, text, fnt)
    draw.text((int(center_x) - w // 2, int(y)), text, font=fnt, fill=tuple(fill))


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont,
         max_width: int, max_lines: int = 3, ellipsis: bool = True) -> list[str]:
    """Greedy word wrap with optional ellipsis on overflow."""
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if text_width(draw, trial, fnt) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    lines = lines[:max_lines]
    if ellipsis and lines:
        consumed = sum(len(l.split()) for l in lines)
        if consumed < len(words):
            last = lines[-1]
            while last and text_width(draw, last + "…", fnt) > max_width:
                last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
            lines[-1] = (last + "…") if last else "…"
    return lines


def line_height(fnt: ImageFont.ImageFont) -> int:
    try:
        ascent, descent = fnt.getmetrics()
        return int(ascent + descent)
    except Exception:
        return int(getattr(fnt, "size", 16) * 1.25)


def top_for_center(fnt: ImageFont.ImageFont, center_y: float) -> int:
    """
    Top-left y that vertically centres this font's em box on ``center_y``.

    Pillow positions text by the top of the ascent box, so drawing two
    different-sized fonts at the same y leaves their visual centres offset by
    half the size difference. Route both through this helper to sit them on a
    shared centre line.
    """
    return int(round(float(center_y) - line_height(fnt) / 2.0))


# ---------------------------------------------------------------------------
# Composite widgets
# ---------------------------------------------------------------------------

def section_header(surface: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int,
                   title: str, *, scale: float = 1.0, subtitle: str | None = None,
                   accent: Sequence[int] = ACCENT) -> int:
    """
    Accent bar + title (+ optional subtitle). Returns the y coordinate just
    below the header block.
    """
    def s(v: float, minimum: int = 1) -> int:
        return max(minimum, int(round(v * scale)))

    title_font = font(s(40, 12), "bold")
    bar_h = line_height(title_font)
    accent_rule(draw, x, y + s(4), s(6), bar_h - s(8), color=accent)
    text_x = x + s(22)
    draw.text((text_x, y), (title or "").upper(), font=title_font, fill=TEXT)
    bottom = y + bar_h + s(4)
    if subtitle:
        sub_font = font(s(24, 10), "medium")
        label(draw, (text_x, bottom), subtitle, sub_font, fill=TEXT_DIM, tracking=s(2, 1))
        bottom += line_height(sub_font) + s(4)
    return bottom


def metric_tile(surface: Image.Image, draw: ImageDraw.ImageDraw, box: Sequence[int],
                name: str, value: str, *, scale: float = 1.0,
                value_color: Sequence[int] = TEXT,
                accent: Sequence[int] | None = None) -> None:
    """A small labelled stat tile used on the current-conditions page."""
    def s(v: float, minimum: int = 1) -> int:
        return max(minimum, int(round(v * scale)))

    x0, y0, x1, y1 = (int(v) for v in box)
    card(surface, (x0, y0, x1, y1), radius=s(18), fill=CARD_FILL_SUNKEN,
         border=CARD_BORDER, shadow=False)
    pad = s(18)
    if accent is not None:
        accent_rule(draw, x0 + pad, y0 + pad, s(4), (y1 - y0) - pad * 2, color=accent)
        pad += s(16)
    label(draw, (x0 + pad, y0 + s(16)), name, font(s(21, 9), "semibold"),
          fill=TEXT_DIM, tracking=s(2, 1))
    draw.text((x0 + pad, y0 + s(44)), value, font=font(s(34, 11), "bold"),
              fill=tuple(value_color))


def sparkline(draw: ImageDraw.ImageDraw, points: Iterable[tuple[int, int]],
              *, color: Sequence[int], width: int = 4,
              glow: bool = True) -> None:
    """Polyline with an optional soft halo underneath for a modern glow."""
    pts = [(int(x), int(y)) for x, y in points]
    if len(pts) < 2:
        return
    if glow:
        draw.line(pts, fill=with_alpha(color, 60), width=max(1, width * 3),
                  joint="curve")
    draw.line(pts, fill=tuple(color), width=max(1, width), joint="curve")


def area_fill(surface: Image.Image, points: Sequence[tuple[int, int]],
              baseline_y: int, color: Sequence[int], *, alpha_top: int = 90) -> None:
    """Gradient area under a line series."""
    pts = [(int(x), int(y)) for x, y in points]
    if len(pts) < 2:
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts] + [int(baseline_y)]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(
        [(x - x0, y - y0) for x, y in pts] + [(x1 - x0, baseline_y - y0), (0, baseline_y - y0)],
        fill=255,
    )
    grad = vertical_gradient((w, h), with_alpha(color, alpha_top), with_alpha(color, 0))
    surface.paste(grad, (x0, y0), mask)


def badge(surface: Image.Image, draw: ImageDraw.ImageDraw, xy: tuple[int, int],
          text: str, *, scale: float = 1.0, fill: Sequence[int] = ACCENT,
          text_color: Sequence[int] = TEXT_ON_ACCENT) -> tuple[int, int]:
    """Small solid pill badge. Returns (width, height) drawn."""
    def s(v: float, minimum: int = 1) -> int:
        return max(minimum, int(round(v * scale)))

    fnt = font(s(20, 9), "bold")
    pad_x, pad_y = s(14), s(7)
    tw = text_width(draw, (text or "").upper(), fnt) + s(2) * max(0, len(text) - 1)
    th = line_height(fnt)
    w = tw + pad_x * 2
    h = th + pad_y * 2
    x, y = int(xy[0]), int(xy[1])
    pill(draw, (x, y, x + w, y + h), fill=fill)
    tracked_text(draw, (x + pad_x, y + pad_y), (text or "").upper(), fnt,
                 fill=text_color, tracking=s(2, 1))
    return (w, h)
