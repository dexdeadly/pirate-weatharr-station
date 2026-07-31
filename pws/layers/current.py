"""Current conditions hero page."""
# Adapted from WeatharrStation by OkinawaBoss:
#   https://github.com/OkinawaBoss/WeatharrStation
#   (originally weatherstream/layers/current.py)
# See NOTICE.md for provenance and licensing status.
from __future__ import annotations

from typing import Any, Callable, Dict

from PIL import ImageDraw

from pws import theme
from pws.core.layer import Layer
from pws.layers.anim_icons import AnimatedIconsMixin


class CurrentLayer(AnimatedIconsMixin, Layer):
    """
    Hero panel: oversized temperature with a condition icon, a high/low and
    sun-times rail, and a grid of secondary metric tiles.

    Consumes the dict produced by ``normalize.build_current`` - every string is
    pre-formatted upstream, so this layer only positions and colours things.
    """

    name = "current"

    def __init__(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        get_data: Callable[[], Dict[str, Any]],
        min_interval: float = 5.0,
        scale: float = 1.0,
    ) -> None:
        super().__init__(x, y, w, h, min_interval=min_interval, scale=scale)
        self.get_data = get_data
        self._init_icons()
        self.min_interval = self._icon_interval()

    def tick(self, now: float):
        try:
            data = self.get_data() or {}
        except Exception:
            data = {}

        state = tuple(sorted((k, str(v)) for k, v in data.items()))
        return self._render_with_icons(now, state, lambda: self._paint(data))

    def _paint(self, data: Dict[str, Any]) -> None:
        surface = self.surface
        surface.paste((0, 0, 0, 0), (0, 0, *surface.size))
        w, h = surface.size

        # ---- hero card ---------------------------------------------------
        hero_h = min(int(h * 0.56), self.s(400, 1))
        theme.card(
            surface, (0, 0, w, hero_h),
            radius=self.s(theme.RADIUS_CARD, 1),
            fill=theme.CARD_FILL_RAISED,
            gradient_to=theme.CARD_FILL,
            border=theme.CARD_BORDER_STRONG,
            border_width=self.s(2, 1),
            shadow_spread=self.s(14, 2),
        )
        draw = ImageDraw.Draw(surface, "RGBA")

        pad = self.s(40)
        temp_f = data.get("temp_f")
        accent = theme.temp_color(temp_f)

        # Condition icon
        icon_size = min(self.s(190, 1), hero_h - self.s(80, 1))
        icon_y = (hero_h - icon_size) // 2
        self._register_icon(pad, icon_y, icon_size,
                            str(data.get("icon") or "clear-day"))
        text_x = pad + icon_size + self.s(36)

        # Huge temperature
        temp_font = theme.font(self.s(150, 30), "black")
        temp_text = str(data.get("temp_display") or "--°")
        temp_y = self.s(38)
        draw.text((text_x, temp_y), temp_text, font=temp_font, fill=accent)
        temp_w = theme.text_width(draw, temp_text, temp_font)

        # Unit suffix riding the top of the number
        unit_font = theme.font(self.s(46, 14), "bold")
        draw.text((text_x + temp_w + self.s(10), temp_y + self.s(26)),
                  str(data.get("temp_unit") or "F"), font=unit_font,
                  fill=theme.with_alpha(accent, 210))

        # Summary + feels like
        sum_font = theme.font(self.s(42, 13), "semibold")
        sum_y = temp_y + theme.line_height(temp_font) - self.s(6)
        summary = str(data.get("summary") or "")
        for line in theme.wrap(draw, summary, sum_font, w - text_x - pad, max_lines=1):
            draw.text((text_x, sum_y), line, font=sum_font, fill=theme.TEXT)

        meta_font = theme.font(self.s(27, 10), "medium")
        meta_y = sum_y + theme.line_height(sum_font) + self.s(6)
        theme.label(draw, (text_x, meta_y),
                    f"Feels like {data.get('feels_display', '--')}  ·  "
                    f"Wind {data.get('wind_display', '--')}",
                    meta_font, fill=theme.TEXT_MUTED, tracking=self.s(1, 1))

        # ---- right rail: high / low / sun --------------------------------
        rail_w = self.s(300, 1)
        rail_x = w - pad - rail_w
        if rail_x > text_x + self.s(200):
            self._draw_rail(surface, draw, rail_x, self.s(34), rail_w,
                            hero_h - self.s(68), data)

        # ---- metric tiles ------------------------------------------------
        tiles = [
            ("Humidity", data.get("humidity_display", "--"), theme.CYAN),
            ("Dew Point", data.get("dew_display", "--"), theme.CYAN),
            ("Pressure", data.get("pressure_display", "--"), theme.VIOLET),
            ("Visibility", data.get("visibility_display", "--"), theme.VIOLET),
            ("UV Index", data.get("uv_display", "--"), theme.AMBER),
            ("Cloud Cover", data.get("cloud_display", "--"), theme.CLOUD),
            ("Chance of Precip", data.get("precip_prob_display", "--"), theme.PRECIP),
            ("Wind Gusts", data.get("gust_display", "--"), theme.LIME),
        ]

        grid_top = hero_h + self.s(24)
        available_h = h - grid_top
        if available_h < self.s(90):
            return

        cols = 4
        rows = 2 if available_h >= self.s(200) else 1
        gap = self.s(16, 1)
        tile_w = (w - gap * (cols - 1)) // cols
        tile_h = min(self.s(100, 1), (available_h - gap * (rows - 1)) // rows)

        for index, (name, value, color) in enumerate(tiles[: cols * rows]):
            col = index % cols
            row = index // cols
            x0 = col * (tile_w + gap)
            y0 = grid_top + row * (tile_h + gap)
            theme.metric_tile(
                surface, draw, (x0, y0, x0 + tile_w, y0 + tile_h),
                name, str(value), scale=self.scale, accent=color,
            )

    # -- sub-components ---------------------------------------------------

    def _draw_rail(self, surface, draw, x: int, y: int, w: int, h: int,
                   data: Dict[str, Any]) -> None:
        """High/low plus sunrise/sunset, stacked in a sunken card."""
        theme.card(
            surface, (x, y, x + w, y + h),
            radius=self.s(18, 1),
            fill=theme.CARD_FILL_SUNKEN,
            border=theme.CARD_BORDER,
            border_width=self.s(2, 1),
            shadow=False,
        )
        draw = ImageDraw.Draw(surface, "RGBA")
        inner_x = x + self.s(24)
        cursor = y + self.s(20)

        label_font = theme.font(self.s(20, 9), "semibold")
        value_font = theme.font(self.s(46, 14), "bold")
        small_font = theme.font(self.s(30, 11), "bold")

        # Today's high / low side by side
        half = (w - self.s(48)) // 2
        for offset, (name, key, fkey, color) in enumerate((
            ("High", "high_display", "high_f", theme.AMBER),
            ("Low", "low_display", "low_f", theme.CYAN),
        )):
            cx = inner_x + offset * half
            theme.label(draw, (cx, cursor), name, label_font,
                        fill=theme.TEXT_DIM, tracking=self.s(2, 1))
            value = str(data.get(key) or "--°")
            tint = theme.temp_color(data.get(fkey)) if data.get(fkey) is not None else color
            draw.text((cx, cursor + self.s(24)), value, font=value_font, fill=tint)

        cursor += self.s(24) + theme.line_height(value_font) + self.s(16)

        # Divider
        draw.line((inner_x, cursor, x + w - self.s(24), cursor),
                  fill=theme.CARD_BORDER, width=self.s(2, 1))
        cursor += self.s(18)

        for name, key, color in (
            ("Sunrise", "sunrise", theme.AMBER),
            ("Sunset", "sunset", theme.ROSE),
        ):
            if cursor + self.s(56) > y + h:
                break
            theme.label(draw, (inner_x, cursor), name, label_font,
                        fill=theme.TEXT_DIM, tracking=self.s(2, 1))
            theme.text_right(draw, (x + w - self.s(24), cursor - self.s(6)),
                             str(data.get(key) or "--"), small_font, fill=color)
            cursor += self.s(46)
