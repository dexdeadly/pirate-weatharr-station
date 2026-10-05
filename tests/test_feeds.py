"""Open-Meteo map cities, NWS alert polling, surf report - HTTP mocked."""
import types

import pytest

from pws import normalize, regional, surf
from pws.nws_alerts import NWSAlertPoller, normalize_feature
from pws.utils import set_timezone


@pytest.fixture(autouse=True)
def _tz():
    set_timezone("America/Chicago", 29.76, -95.37)


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_wmo_codes_map_to_icons():
    assert regional.describe(0, True) == ("Clear", "clear-day")
    assert regional.describe(0, False) == ("Clear", "clear-night")
    assert regional.describe(95)[1] == "thunderstorm"
    assert regional.describe(999, False)[1] == "clear-night"


def test_regional_fetch_shapes_points(monkeypatch):
    rows = [{"current": {"temperature_2m": 72.4, "weather_code": 2, "is_day": 1},
             "daily": {"temperature_2m_max": [85.4, 88.4], "weather_code": [1, 63]}}] * 2
    monkeypatch.setattr(regional.requests, "get", lambda *a, **k: Resp(200, rows))
    targets = [{"name": "Austin", "lat": 30.27, "lon": -97.74},
               {"name": "San Antonio", "lat": 29.42, "lon": -98.49}]
    cur, fc = regional.fetch(targets, normalize.units_for("us"), "ua", forecast_day=1)
    assert [c["temp"] for c in cur] == ["72°", "72°"]
    assert cur[0]["icon"] == "partly-cloudy-day"
    assert [f["forecast_temp"] for f in fc] == ["88°", "88°"]
    assert fc[0]["forecast_short"] == "Rain"


def test_regional_fetch_failure_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(regional.requests, "get", boom)
    assert regional.fetch([{"name": "X", "lat": 1, "lon": 1}], normalize.units_for("us"), "ua") is None


def test_nws_feature_filtering():
    base = {"event": "Flood Watch", "headline": "Flood Watch issued x", "severity": "Severe",
            "status": "Actual", "messageType": "Alert", "areaDesc": "A; B; C; D; E"}
    alert = normalize_feature(base)
    assert alert["level"] == "warning"
    assert alert["regions"] == "A, B, C and more"
    assert normalize_feature({**base, "status": "Test"}) is None
    assert normalize_feature({**base, "messageType": "Cancel"}) is None


def test_nws_poller_outside_us_falls_back(monkeypatch):
    poller = NWSAlertPoller(51.5, -0.12, "ua")
    monkeypatch.setattr(poller._session, "get", lambda *a, **k: Resp(400, {}))
    poller.poll_once()
    assert poller.alerts() is None          # caller falls back to Pirate alerts


def test_nws_poller_dedupes_and_sorts(monkeypatch):
    feats = [{"properties": {"event": "Flood Watch", "headline": "Flood Watch issued 1",
                             "severity": "Severe", "status": "Actual", "ends": "2026-10-02T19:00:00-05:00"}},
             {"properties": {"event": "Flood Watch", "headline": "Flood Watch issued 2",
                             "severity": "Severe", "status": "Actual", "ends": "2026-10-02T19:00:00-05:00"}},
             {"properties": {"event": "Tornado Warning", "headline": "Tornado Warning issued 3",
                             "severity": "Extreme", "status": "Actual"}}]
    poller = NWSAlertPoller(29.76, -95.37, "ua")
    monkeypatch.setattr(poller._session, "get", lambda *a, **k: Resp(200, {"features": feats}))
    poller.poll_once()
    alerts = poller.alerts()
    assert [a["level"] for a in alerts] == ["alert", "warning"]


def test_surf_helpers():
    assert surf.compass(0) == "N" and surf.compass(250) == "WSW" and surf.compass(None) == "--"
    low, high = surf.surf_range(3.0, 12.0)
    assert 0 < low < high
    assert surf.rate(0.5, 10, 5) == "FLAT"
    assert surf.rate(5, 13, 5) in ("GOOD", "EPIC")
    assert surf.rate(5, 13, 25) in ("POOR", "FAIR")      # strong wind knocks it down


def test_surf_report_inland_message():
    client = types.SimpleNamespace(imperial_length=True, units="us",
                                   marine=lambda: {"current": {}}, wind=lambda: {}, tides=lambda: None)
    report = surf.build_report(client, "Inland")
    assert report["available"] is False and "No marine forecast" in report["message"]
