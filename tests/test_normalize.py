from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from pws import normalize
from pws.utils import set_clock_24h, set_timezone

TZ = ZoneInfo("America/Chicago")
DAY0 = datetime(2026, 10, 2, tzinfo=TZ)


@pytest.fixture(autouse=True)
def _tz():
    set_timezone("America/Chicago", 29.76, -95.37)
    set_clock_24h(False)
    yield
    set_clock_24h(False)


def payload(hour, temp, hourly_step=-0.8):
    now = DAY0 + timedelta(hours=hour)
    return {
        "currently": {"time": now.timestamp(), "temperature": temp},
        "hourly": {"data": [{"time": (now + timedelta(hours=i)).timestamp(),
                             "temperature": temp + i * hourly_step} for i in range(48)]},
        "daily": {"data": [{"time": (DAY0 + timedelta(days=d)).timestamp(),
                            "temperatureHigh": 88 + d, "temperatureLow": 70 + d} for d in range(7)]},
    }


US = normalize.units_for("us")


@pytest.mark.parametrize("hour,high_period,high,low_period,low", [
    (14, "Today", "88°", "Tonight", "70°"),
    (21, "Tomorrow", "89°", "Tonight", "70°"),
    (3, "Today", "88°", "Overnight", "64°"),   # 66.4 falling 0.8/h to 6 am
])
def test_high_low_follows_time_of_day(hour, high_period, high, low_period, low):
    cur = normalize.build_current(payload(hour, 66.4 if hour == 3 else 80), US, "Houston")
    assert (cur["high_period"], cur["high_display"]) == (high_period, high)
    assert (cur["low_period"], cur["low_display"]) == (low_period, low)


def test_extended_forecast_starts_tomorrow_after_6pm():
    assert [p["name"] for p in normalize.build_forecast_periods(payload(14, 80), US)][0] == "Today"
    assert [p["name"] for p in normalize.build_forecast_periods(payload(21, 80), US)][0] == "Tomorrow"


def test_pressure_units():
    assert normalize._pressure(1016.4, US) == "30.01 inHg"
    assert normalize._pressure(1016.4, normalize.units_for("si")) == "1016 hPa"
    assert normalize._pressure(None, US) == "--"


@pytest.mark.parametrize("title,severity,level", [
    ("Tornado Warning issued ...", "Extreme", "alert"),
    ("Flood Watch issued ...", "Severe", "warning"),       # event beats severity
    ("Heat Advisory issued ...", "Moderate", "warning"),
    ("Civil Emergency Message", "Unknown", "alert"),
    ("Something Odd", "Severe", "alert"),
    ("Something Odd", "Minor", "warning"),
])
def test_alert_levels(title, severity, level):
    assert normalize.alert_level(title, severity) == level


def test_alerts_sorted_most_serious_first():
    alerts = normalize.build_alerts({"alerts": [
        {"title": "Flood Watch issued x", "severity": "Severe"},
        {"title": "Tornado Warning issued y", "severity": "Extreme"},
    ]})
    assert [a["level"] for a in alerts] == ["alert", "warning"]
    assert normalize.alerts_level(alerts) == "alert"
    assert normalize.alerts_level([]) == "none"


def test_clock_formats():
    t = datetime(2026, 10, 2, 14, 5, tzinfo=TZ).timestamp()
    assert normalize._clock(t) == "2:05 PM"
    assert normalize._hour_label(t) == "2P"
    set_clock_24h(True)
    assert normalize._clock(t) == "14:05"
    assert normalize._hour_label(t) == "14"


def test_until_label_adds_weekday_when_not_today():
    tomorrow = (datetime.now(TZ) + timedelta(days=1)).replace(hour=19, minute=0)
    label = normalize.until_label(tomorrow.timestamp())
    assert label.endswith("7:00 PM") and label.split()[0] == tomorrow.strftime("%a")
