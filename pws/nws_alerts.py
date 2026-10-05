"""
Fast NWS alert polling, independent of the forecast refresh.

Alerts used to arrive only inside the Pirate Weather forecast call, which is
cached for the station's refresh interval multiplied by the number of stations
(10 min x 3 = 30 min). A tornado warning could reach the screen half an hour
late. The NWS publishes the same alerts on a free, keyless API that costs no
Pirate Weather quota, so poll it every minute for US locations.

https://www.weather.gov/documentation/services-web-api (alerts/active?point=)
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Optional

import requests

from pws import normalize

ALERTS_URL = "https://api.weather.gov/alerts/active"
PROJECT_URL = "https://github.com/dexdeadly/pirate-weatharr-station"

#: NWS asks clients not to poll more than about every 30 s.
POLL_SEC = 60
#: Older than this and the poller stops vouching for its list, so callers fall
#: back to the alerts inside the Pirate Weather payload.
FRESH_SEC = 300
#: Areas named in the alert bar before trailing off; areaDesc can list dozens.
MAX_AREAS = 3


def _epoch(iso: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def normalize_feature(props: dict) -> Optional[dict]:
    """One NWS alert -> the dict shape normalize.build_alerts produces."""
    if (props.get("status") or "Actual") != "Actual":
        return None  # tests, exercises, drafts
    if props.get("messageType") == "Cancel":
        return None
    event = str(props.get("event") or "").strip()
    title = str(props.get("headline") or event).strip()
    if not title:
        return None
    severity = str(props.get("severity") or "Unknown").title()
    areas = [a.strip() for a in str(props.get("areaDesc") or "").split(";") if a.strip()]
    regions = ", ".join(areas[:MAX_AREAS]) + (" and more" if len(areas) > MAX_AREAS else "")
    return {
        "title": title,
        "severity": severity,
        # Classify on the event name ("Flood Watch"), not the long headline.
        "level": normalize.alert_level(event or title, severity),
        "regions": regions,
        "expires": normalize.until_label(_epoch(props.get("ends") or props.get("expires"))),
        "description": str(props.get("description") or "").strip(),
        "id": str(props.get("id") or ""),
    }


class NWSAlertPoller:
    """
    Background poller for one point. ``alerts()`` returns the current list
    while fresh, or ``None`` when the poller can't vouch for it (outside the
    US, NWS unreachable, not yet polled) so callers fall back.
    """

    def __init__(self, lat: float, lon: float, user_agent: str,
                 interval: float = POLL_SEC) -> None:
        self.point = f"{float(lat):.4f},{float(lon):.4f}"
        self.interval = max(30.0, float(interval))
        self._session = requests.Session()
        # NWS requires a User-Agent identifying the application.
        self._session.headers.update({
            "User-Agent": user_agent if "http" in user_agent else f"{user_agent} (+{PROJECT_URL})",
            "Accept": "application/geo+json",
        })
        self._lock = threading.Lock()
        self._alerts: list[dict] = []
        self._ok_at = 0.0
        self._unsupported = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="nws-alerts", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set() and not self._unsupported:
            self.poll_once()
            self._stop.wait(self.interval)

    # -- polling ----------------------------------------------------------

    def poll_once(self) -> None:
        try:
            resp = self._session.get(ALERTS_URL, params={"point": self.point}, timeout=15)
        except requests.RequestException as exc:
            print(f"[alerts] NWS poll failed: {exc.__class__.__name__}", flush=True)
            return
        if resp.status_code in (400, 404):
            # The NWS only covers US points; stop polling and let the Pirate
            # Weather alerts (which carry the same data where it exists) stand.
            self._unsupported = True
            print("[alerts] location outside NWS coverage; using Pirate Weather alerts",
                  flush=True)
            return
        if resp.status_code != 200:
            print(f"[alerts] NWS poll HTTP {resp.status_code}", flush=True)
            return
        try:
            features = (resp.json() or {}).get("features") or []
        except ValueError:
            return
        alerts, seen = [], set()
        for feature in features:
            alert = normalize_feature((feature or {}).get("properties") or {})
            if not alert:
                continue
            # Updates re-issue an alert under a new id; one line per event+headline.
            key = (alert["title"].split(" issued ")[0], alert["expires"])
            if key in seen:
                continue
            seen.add(key)
            alerts.append(alert)
        alerts.sort(key=lambda a: 0 if a["level"] == normalize.ALERT_LEVEL_ALERT else 1)
        with self._lock:
            if [a["title"] for a in alerts] != [a["title"] for a in self._alerts]:
                print(f"[alerts] {len(alerts)} active NWS alert(s)", flush=True)
            self._alerts = alerts
            self._ok_at = time.time()

    def alerts(self) -> Optional[list[dict]]:
        with self._lock:
            if self._unsupported or time.time() - self._ok_at > FRESH_SEC:
                return None
            return list(self._alerts)
