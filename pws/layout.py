"""
Shared header geometry.

The header is a four-column band. Chrome paints columns 1 and 2 plus the
dividers; the current-conditions and clock layers each own one of the remaining
columns. Everything derives from this one function so the columns can never
drift out of alignment with each other.

    | 1 identity | 2 page title | 3 currently | 4 local time |
"""
from __future__ import annotations

from typing import Callable

#: Header band height in design units (1920x1080 reference).
HEADER_H = 176

#: Vertical rhythm shared by every column.
LABEL_Y = 40      # small caps column label
BODY_Y = 66       # start of the column's main content
BAND_TOP = 30     # divider top
BAND_BOTTOM = 166  # divider bottom

_PAD_LEFT = 56
_PAD_RIGHT = 48
_GAP = 36

#: Relative widths: identity, page title, currently, local time.
#: Equal quarters, so the band reads as an even four-up grid. Content is
#: centred inside columns 2 and 3; column 1 stays flush to the left page
#: margin and column 4 flush to the right, keeping the outer edges aligned
#: with the content cards below.
_WEIGHTS = (0.25, 0.25, 0.25, 0.25)


def header_columns(width: int, s: Callable[..., int]) -> list[tuple[int, int]]:
    """
    Return ``[(x, width), ...]`` for the four header columns.

    ``s`` is the caller's scale helper (``Layer.s``) so the same layout holds at
    480p through 4K.
    """
    left = s(_PAD_LEFT)
    right = max(left + 4, width - s(_PAD_RIGHT))
    gap = s(_GAP)
    available = max(4, (right - left) - gap * 3)

    widths = [max(1, int(available * w)) for w in _WEIGHTS]
    # Give any rounding remainder to the last column so it ends flush right.
    widths[-1] = max(1, available - sum(widths[:-1]))

    columns: list[tuple[int, int]] = []
    x = left
    for w in widths:
        columns.append((x, w))
        x += w + gap
    return columns


def divider_positions(width: int, s: Callable[..., int]) -> list[int]:
    """X coordinates of the hairlines sitting in each inter-column gap."""
    columns = header_columns(width, s)
    gap = s(_GAP)
    return [x + w + gap // 2 for x, w in columns[:-1]]
