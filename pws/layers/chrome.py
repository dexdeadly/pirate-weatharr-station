"""Background chrome: gradient field, four-column header, footer tray."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/chrome.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from typing import Callable, Optional, Sequence

from PIL import ImageDraw

from pws import layout, theme
from pws.core.layer import Layer


class ChromeLayer(Layer):
    """
    The static frame every page sits inside.

    Paints the background field and header columns 1 (station identity) and 2
    (page title), plus the dividers separating all four columns. Columns 3 and 4
    are owned by the current-conditions and clock layers, which update far more
    often than this one does.
    """

    name = "chrome"
    z = 0

    def __init__(
        self,
        *,
        width: int,
        height: int,
        location_name: str,
        page_title: str = "",
        title: str = "PWS",
        wordmark: str = "Pirate Weather Station",
        provider: str = "Pirate Weather",
        get_alerts: Optional[Callable[[], Sequence[dict]]] = None,
        min_interval: float = 5.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(0, 0, width, height, min_interval=min_interval, scale=scale)
        self.location = location_name or ""
        self.page_title = page_title or ""
        self.title = title
        self.wordmark = wordmark
        self.provider = provider
        self.get_alerts = get_alerts
        self._state: tuple | None = None
        self._painted = False

    # -- helpers ----------------------------------------------------------

    def _top_alert(self) -> dict | None:
        if not callable(self.get_alerts):
            return None
        try:
            alerts = self.get_alerts() or []
        except Exception:
            return None
        if not alerts:
            return None
        rank = {"extreme": 4, "severe": 3, "moderate": 2, "minor": 1}
        return max(alerts, key=lambda a: rank.get(str(a.get("severity", "")).lower(), 0))

    def tick(self, now: float):
        alert = self._top_alert()
        state = ((alert or {}).get("title"), (alert or {}).get("severity"),
                 self.page_title, self.location)
        if self._painted and state == self._state:
            return []
        self._state = state
        self._painted = True

        surface = self.surface
        theme.paint_background(surface)
        draw = ImageDraw.Draw(surface, "RGBA")
        w = surface.width
        header_h = self.s(layout.HEADER_H, 1)

        # --- header band --------------------------------------------------
        band = theme.vertical_gradient((w, header_h), theme.HEADER_TOP,
                                       theme.HEADER_BOTTOM)
        surface.paste(band, (0, 0))
        draw.rectangle((0, header_h - self.s(3, 1), w, header_h),
                       fill=theme.with_alpha(theme.ACCENT, 150))

        columns = layout.header_columns(w, self.s)
        self._draw_identity(surface, draw, *columns[0])
        self._draw_page_title(draw, *columns[1])

        for x in layout.divider_positions(w, self.s):
            draw.line((x, self.s(layout.BAND_TOP), x, self.s(layout.BAND_BOTTOM)),
                      fill=theme.with_alpha(theme.TEXT_DIM, 70), width=self.s(2, 1))

        if alert:
            self._draw_alert(surface, alert, header_h, w)

        # --- footer ticker tray ---------------------------------------------
        tray_h = self.s(64, 1)
        tray_y = surface.height - tray_h - self.s(22)
        theme.card(
            surface, (self.s(48), tray_y, w - self.s(48), tray_y + tray_h),
            radius=self.s(18, 1), fill=theme.CARD_FILL_SUNKEN,
            border=theme.CARD_BORDER, border_width=self.s(2, 1),
            shadow_spread=self.s(8, 1),
        )
        return self._mark_all_dirty_if_changed()

    # -- column 1: station identity ---------------------------------------

    def _draw_identity(self, surface, draw, x: int, w: int) -> None:
        """
        Logo mark + PWS lockup, station name, and location.

        The logo carries the Pirate Weather branding, so the separate
        "powered by" chip that used to sit here would be redundant; provider
        attribution is now the mark itself.
        """
        cursor_x = x
        mark_h = self.s(78, 1)
        mark = theme.logo(mark_h)
        if mark is not None:
            surface.alpha_composite(mark, dest=(cursor_x, self.s(20)))
            # Hairline keyline so the artwork reads as a deliberate tile
            # against the header gradient.
            draw.rectangle(
                (cursor_x, self.s(20), cursor_x + mark.width - 1,
                 self.s(20) + mark_h - 1),
                outline=theme.with_alpha(theme.CARD_BORDER_STRONG, 120),
                width=self.s(2, 1),
            )
            cursor_x += mark.width + self.s(18)
        else:
            # No logo bundled: fall back to the original accent bar.
            theme.accent_rule(draw, cursor_x, self.s(28), self.s(8), self.s(58, 1))
            cursor_x += self.s(24)

        title_font = theme.font(self.s(50, 14), "black")
        draw.text((cursor_x, self.s(24)), self.title, font=title_font, fill=theme.TEXT)

        if self.wordmark:
            # Fit the wordmark into whatever space the lockup leaves.
            mark_y = self.s(24) + theme.line_height(title_font) - self.s(4)
            available = (x + w) - cursor_x
            text = self.wordmark.upper()
            for size, track in ((17, 2), (16, 1), (14, 1), (13, 1)):
                mark_font = theme.font(self.s(size, 8), "semibold")
                tracking = self.s(track, 1)
                if theme.tracked_width(draw, text, mark_font, tracking) <= available:
                    theme.tracked_text(draw, (cursor_x, mark_y), text, mark_font,
                                       fill=theme.TEXT_DIM, tracking=tracking)
                    break

        loc_font = theme.font(self.s(27, 11), "medium")
        theme.label(draw, (x, self.s(114)), self.location, loc_font,
                    fill=theme.TEXT_MUTED, tracking=self.s(3, 1))

    # -- column 2: page title ---------------------------------------------

    def _draw_page_title(self, draw, x: int, w: int) -> None:
        cx = x + w // 2
        label_font = theme.font(self.s(18, 8), "semibold")
        theme.tracked_center(draw, cx, self.s(layout.LABEL_Y), "NOW SHOWING",
                             label_font, fill=theme.TEXT_DIM, tracking=self.s(3, 1))
        if not self.page_title:
            return

        text = self.page_title.upper()
        # Step the size down before resorting to wrapping.
        for size in (36, 32, 28):
            font = theme.font(self.s(size, 12), "bold")
            tracking = self.s(3, 1)
            if theme.tracked_width(draw, text, font, tracking) <= w:
                theme.tracked_center(draw, cx, self.s(layout.BODY_Y), text, font,
                                     fill=theme.TEXT, tracking=tracking)
                return

        font = theme.font(self.s(28, 11), "bold")
        y = self.s(layout.BODY_Y)
        for line in theme.wrap(draw, text, font, w, max_lines=2):
            theme.tracked_center(draw, cx, y, line, font, fill=theme.TEXT,
                                 tracking=self.s(2, 1))
            y += theme.line_height(font) + self.s(4)

    # -- alert banner ------------------------------------------------------

    def _draw_alert(self, surface, alert: dict, header_h: int, w: int) -> None:
        color = theme.severity_color(alert.get("severity"))
        pad_x = self.s(56)
        banner_y = header_h + self.s(10)
        banner_h = self.s(56, 1)
        theme.card(
            surface, (pad_x, banner_y, w - self.s(48), banner_y + banner_h),
            radius=self.s(14, 1),
            fill=theme.with_alpha(color, 46),
            border=theme.with_alpha(color, 170),
            border_width=self.s(2, 1), shadow=False,
        )
        draw = ImageDraw.Draw(surface, "RGBA")
        bx = pad_x + self.s(20)
        badge_w, badge_h = theme.badge(
            surface, draw, (bx, banner_y + (banner_h - self.s(36, 1)) // 2),
            str(alert.get("severity") or "Alert"), scale=self.scale, fill=color,
        )
        headline = str(alert.get("title") or "").split(" issued ")[0].strip()
        expires = alert.get("expires")
        if expires and expires != "--":
            headline = f"{headline}  ·  until {expires}"

        font = theme.font(self.s(26, 10), "semibold")
        text_x = bx + badge_w + self.s(18)
        max_w = (w - self.s(48)) - text_x - self.s(20)
        lines = theme.wrap(draw, headline, font, max_w, max_lines=1)
        if lines:
            text_y = banner_y + (banner_h - theme.line_height(font)) // 2
            draw.text((text_x, text_y), lines[0], font=font, fill=theme.TEXT)
