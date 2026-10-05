"""Persistent, colour-coded alert bar between the header band and the page."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from PIL import ImageDraw

from pws import normalize, theme
from pws.core.layer import Layer
from pws.utils import fmt_time, to_local

_LEVEL_LABEL = {
    normalize.ALERT_LEVEL_NONE: "NO ALERTS",
    normalize.ALERT_LEVEL_WARNING: "WARNING",
    normalize.ALERT_LEVEL_ALERT: "ALERT",
}


class AlertBarLayer(Layer):
    """
    Always-on strip showing the station's alert status on every page.

    Three tiers, each with its own colour: NO ALERTS (green), WARNING (amber,
    watches/advisories) and ALERT (red, warnings/emergencies). With several
    alerts active it rotates through them most-serious first, holding each for
    ``rotate_sec``, and shows "n of N" so viewers know there is more.
    """

    name = "alert_bar"

    def __init__(
        self,
        *,
        x: int,
        y: int,
        w: int,
        h: int,
        get_alerts: Callable[[], Sequence[dict]],
        get_error: Optional[Callable[[], Optional[str]]] = None,
        get_updated: Optional[Callable[[], Optional[float]]] = None,
        stale_after_sec: float = 1800.0,
        rotate_sec: float = 8.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=1.0, scale=scale)
        self.get_alerts = get_alerts
        self.get_error = get_error
        self.get_updated = get_updated
        self.stale_after_sec = max(60.0, float(stale_after_sec))
        self.rotate_sec = max(2.0, float(rotate_sec))
        self._state: tuple | None = None

    def tick(self, now: float):
        try:
            alerts = list(self.get_alerts() or [])
        except Exception:
            alerts = []
        index = int(now // self.rotate_sec) % len(alerts) if alerts else 0
        alert = alerts[index] if alerts else None
        # Colour follows the alert on screen; alerts are sorted most-serious
        # first, so the bar opens on the highest tier before rotating down.
        level = normalize.alerts_level([alert] if alert else [])
        error = None
        if not alerts and callable(self.get_error):
            try:
                error = self.get_error()
            except Exception:
                error = None

        if error:
            # Never show a green all-clear when we simply don't know.
            level = "unknown"

        freshness = self._freshness()
        state = (level, index, len(alerts),
                 (alert or {}).get("title"), (alert or {}).get("expires"), error, freshness)
        if state == self._state:
            return []
        self._state = state
        self._paint(level, alert, index, len(alerts), error, freshness)
        w, h = self.surface.size
        return [(0, 0, w, h)]

    def _freshness(self) -> Optional[tuple[str, bool]]:
        """('10:42 AM', stale?) for the forecast on screen, or None if unknown."""
        if not callable(self.get_updated):
            return None
        try:
            updated = self.get_updated()
        except Exception:
            return None
        if not updated:
            return None
        label = fmt_time(to_local(datetime.fromtimestamp(float(updated), tz=timezone.utc)))
        return (label, time.time() - float(updated) > self.stale_after_sec)

    def _paint(self, level: str, alert: Optional[dict], index: int, count: int,
               error: Optional[str], freshness: Optional[tuple[str, bool]] = None) -> None:
        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        w, h = surface.size
        color = theme.TEXT_DIM if level == "unknown" else theme.alert_level_color(level)

        theme.card(
            surface, (0, 0, w, h),
            radius=self.s(14, 1),
            fill=theme.with_alpha(color, 40),
            border=theme.with_alpha(color, 180),
            border_width=self.s(2, 1), shadow=False,
        )
        draw = ImageDraw.Draw(surface, "RGBA")
        # Solid tier stripe on the leading edge so the colour reads even at a glance.
        draw.rectangle((0, 0, self.s(10, 2), h - 1), fill=color)

        pad = self.s(24)
        badge_h_est = self.s(36, 1)
        badge_w, _ = theme.badge(
            surface, draw, (pad, (h - badge_h_est) // 2),
            _LEVEL_LABEL.get(level, "NO DATA"), scale=self.scale, fill=color,
        )
        text_x = pad + badge_w + self.s(18)
        right = w - pad

        # Forecast freshness on the far right: dim "Updated 10:42 AM", or an
        # amber DATA DELAYED once it's older than stale_after_sec (the client
        # keeps serving its last good forecast when refreshes fail).
        if freshness:
            stamp, stale = freshness
            fresh_font = theme.font(self.s(19, 8), "semibold")
            text_f = f"DATA DELAYED · {stamp}" if stale else f"UPDATED {stamp}"
            fw = theme.tracked_width(draw, text_f, fresh_font, self.s(1, 1))
            theme.tracked_text(
                draw, (right - fw, theme.top_for_center(fresh_font, h / 2)), text_f,
                fresh_font, fill=theme.ALERT_WARNING if stale else theme.TEXT_DIM,
                tracking=self.s(1, 1),
            )
            right -= fw + self.s(28)

        if count > 1:
            counter_font = theme.font(self.s(20, 8), "semibold")
            counter = f"{index + 1} OF {count}"
            cw = theme.tracked_width(draw, counter, counter_font, self.s(2, 1))
            theme.tracked_text(
                draw, (right - cw, theme.top_for_center(counter_font, h / 2)),
                counter, counter_font, fill=theme.TEXT_MUTED, tracking=self.s(2, 1),
            )
            right -= cw + self.s(24)

        if alert:
            text = str(alert.get("title") or "").split(" issued ")[0].strip()
            expires = alert.get("expires")
            if expires and expires != "--":
                text = f"{text}  ·  until {expires}"
            regions = str(alert.get("regions") or "").strip()
            if regions:
                text = f"{text}  ·  {regions}"
            fill = theme.TEXT
        elif error:
            text = "Alert status unavailable - weather data could not be refreshed"
            fill = theme.TEXT_MUTED
        else:
            text = "No active weather alerts for this area"
            fill = theme.TEXT_MUTED

        font = theme.font(self.s(26, 10), "semibold")
        lines = theme.wrap(draw, text, font, max(1, right - text_x), max_lines=1)
        if lines:
            draw.text((text_x, theme.top_for_center(font, h / 2)), lines[0],
                      font=font, fill=fill)
