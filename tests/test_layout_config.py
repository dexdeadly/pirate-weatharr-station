import pytest

from pws import layout
from pws.config import PAGE_NAMES, parse_args, parse_pages


@pytest.mark.parametrize("scale", [1.0, 2 / 3, 0.4448, 2.0])
def test_alert_bar_gaps_are_even(scale):
    s = lambda v, m=0: max(m, int(round(v * scale)))
    y = layout.alert_bar_y(s)
    above = y - s(layout.HEADER_H)
    below = s(layout.CONTENT_TOP) - (y + s(layout.ALERT_BAR_H, 1))
    assert above >= 0 and below >= 0 and abs(above - below) <= 1


def test_parse_pages():
    assert parse_pages("") == list(PAGE_NAMES)
    assert parse_pages("daily, current radar") == ["daily", "current", "radar"]
    assert parse_pages("Forecast-Map,bogus,daily,daily") == ["forecast_map", "daily"]


@pytest.mark.parametrize("args,expected", [
    (["--units", "us"], False), (["--units", "si"], True),
    (["--units", "us", "--clock", "24"], True), (["--units", "si", "--clock", "12"], False),
])
def test_clock_auto(args, expected):
    assert parse_args(["--api-key", "k"] + args).clock_24h is expected
