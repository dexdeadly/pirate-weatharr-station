"""
PWS - Pirate Weather Station

Dispatcharr plugin that runs a local TV-style weather channel driven by the
Pirate Weather API and publishes it as a channel.

Settings are deliberately minimal. Everything the API can tell us, we ask the
API rather than the user: the timezone, city name and elevation all come back in
the same forecast call, so there are no fields for them.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

from apps.channels.models import Channel, ChannelGroup, ChannelStream, Stream
from apps.plugins.models import PluginConfig
from core.models import StreamProfile

try:
    from pws.data.zipcodes import resolve_zip
except Exception:  # pragma: no cover - assets missing
    resolve_zip = None

try:  # pragma: no cover - Unix only
    import fcntl
except Exception:  # pragma: no cover - Windows
    fcntl = None


_START_LOCK = threading.Lock()

#: How many independent stations (each its own channel) the plugin offers.
_STATION_COUNT = 3

#: Station N listens on _BASE_PORT + (N - 1).
_BASE_PORT = 5960

#: Settings keys owned by the running process rather than the user.
_RUNTIME_FIELDS = (
    "pid",
    "running",
    "run_token",
    "pid_started_at",
    "last_started_at",
    "last_stopped_at",
    "stream_id",
    "channel_id",
    "resolved_channel_number",
    "location_label",
    "output_url",
    "encoding",
)

def _station_field_id(idx: int, field: str) -> str:
    """
    Settings key for a per-station field.

    Station 1 keeps the unsuffixed keys the single-station build used, so an
    existing install keeps its configuration when upgrading.
    """
    if field == "enabled":
        return f"station_{idx}_enabled"
    return field if idx == 1 else f"station_{idx}_{field}"


def _station_runtime_key(idx: int, field: str) -> str:
    """Settings key for per-station runtime state (pid, ids, and so on)."""
    return field if idx == 1 else f"station_{idx}_{field}"


_RESOLUTIONS = [
    {"value": "3840x2160", "label": "4K (3840x2160)"},
    {"value": "1920x1080", "label": "1080p (1920x1080)"},
    {"value": "1280x720", "label": "720p (1280x720)"},
    {"value": "854x480", "label": "480p (854x480)"},
]

_RADAR_SOURCES = [
    {"value": "noaa", "label": "NOAA / NWS (US only)"},
    {"value": "rainviewer", "label": "RainViewer (worldwide)"},
    {"value": "auto", "label": "Auto (NOAA, fall back to RainViewer)"},
    {"value": "off", "label": "Off (hide the radar page)"},
]

_UNITS = [
    {"value": "us", "label": "Imperial (°F, mph, mi)"},
    {"value": "ca", "label": "Metric (°C, km/h, km)"},
    {"value": "si", "label": "SI (°C, m/s, km)"},
    {"value": "uk", "label": "UK (°C, mph, mi)"},
]



_SHARED_FIELDS: list[dict[str, Any]] = [
    {
        "id": "setup_info",
        "label": "Setup",
        "type": "info",
        "description": (
            "Create a free API key at pirateweather.net, subscribe to the "
            "Forecast API, then enter the key and at least one ZIP code below. "
            "Activation of a new key can take up to 20 minutes. Each enabled "
            "station becomes its own channel."
        ),
    },
    {
        "id": "api_key",
        "label": "Pirate Weather API Key",
        "type": "string",
        "default": "",
        "help_text": "Required. Shared by every station and kept out of the command line.",
    },
    {
        "id": "units",
        "label": "Units",
        "type": "select",
        "default": "us",
        "options": _UNITS,
        "help_text": "Unit system used for all on-screen values.",
    },
    {
        "id": "resolution",
        "label": "Resolution",
        "type": "select",
        "default": "1920x1080",
        "options": _RESOLUTIONS,
        "help_text": "Output resolution for every station.",
    },
    {
        "id": "video_kbps",
        "label": "Video Bitrate (kbps)",
        "type": "number",
        "default": 3500,
        "min": 500,
        "max": 20000,
        "step": 100,
        "help_text": "Target video bitrate per station.",
    },
    {
        "id": "radar_source",
        "label": "Radar Source",
        "type": "select",
        "default": "noaa",
        "options": _RADAR_SOURCES,
        "help_text": (
            "Pirate Weather serves no radar imagery, so radar comes from a "
            "separate provider. NOAA covers the US only; RainViewer is "
            "worldwide. The on-screen credit follows whichever is used."
        ),
    },
    {
        "id": "music_volume",
        "label": "Background Music Volume",
        "type": "number",
        "default": 50,
        "min": 0,
        "max": 100,
        "step": 5,
        "help_text": (
            "0 disables music. NOTE: no audio ships with the plugin - drop "
            "your own .mp3/.m4a/.aac/.flac/.ogg/.wav files into the plugin's "
            "assets/music folder, then restart. They are shuffled and looped. "
            "pws.log records how many tracks were found."
        ),
    },
    {
        "id": "rss_urls",
        "label": "News Ticker Feeds",
        "type": "string",
        "default": "",
        "help_text": (
            "Optional RSS/Atom URLs, comma separated, shared by every station. "
            "Weather alerts always appear in the ticker regardless."
        ),
    },
]


def _build_fields() -> list[dict[str, Any]]:
    """Shared settings, then one configuration block per station."""
    fields: list[dict[str, Any]] = [deepcopy(f) for f in _SHARED_FIELDS]
    for idx in range(1, _STATION_COUNT + 1):
        fields.append({
            "id": f"station_{idx}_info",
            "label": f"Station {idx}",
            "type": "info",
            "description": (
                "The primary station." if idx == 1
                else "Optional additional station and channel."
            ),
        })
        fields.append({
            "id": _station_field_id(idx, "enabled"),
            "label": f"Enable Station {idx}",
            "type": "boolean",
            "default": idx == 1,
            "help_text": (
                "Each enabled station runs its own renderer and channel. "
                "Refresh intervals are shared out between them so the monthly "
                "API quota stays the same no matter how many you run."
            ),
        })
        fields.append({
            "id": _station_field_id(idx, "zip_code"),
            "label": f"Station {idx} ZIP Code",
            "type": "string",
            "default": "",
            "help_text": "5-digit US ZIP used to locate the forecast.",
        })
        fields.append({
            "id": _station_field_id(idx, "location_name"),
            "label": f"Station {idx} Location Name",
            "type": "string",
            "default": "",
            "help_text": "Optional on-screen name. Resolved from the ZIP if blank.",
        })
        fields.append({
            "id": _station_field_id(idx, "channel_number"),
            "label": f"Station {idx} Channel Number",
            "type": "number",
            "default": "",
            "help_text": "Optional channel number. Auto-assigned when blank.",
        })
    return fields


class Plugin:
    name = "PWS - Pirate Weather Station"
    version = "1.1.2"
    description = (
        "TV-style weather channels powered by the Pirate Weather API. Runs up "
        "to three stations, each with its own location and Dispatcharr channel."
    )
    author = "PWS"
    help_url = "https://pirateweather.net/"

    # -- settings ---------------------------------------------------------
    # Shared settings first, then one block per station. Station 1 uses the
    # unsuffixed keys so existing single-station installs upgrade cleanly.
    fields = _build_fields()

    actions = [
        {
            "id": "start",
            "label": "Start",
            "description": "Launch the PWS renderer and publish the channel.",
            "button_label": "Start",
            "button_color": "green",
        },
        {
            "id": "stop",
            "label": "Stop",
            "description": "Terminate the PWS renderer.",
            "button_label": "Stop",
            "button_color": "yellow",
            "confirm": {
                "required": True,
                "title": "Stop PWS?",
                "message": "This will terminate the running PWS feed.",
            },
        },
        {
            "id": "reset_defaults",
            "label": "Reset to Defaults",
            "description": "Stop the renderer and restore default settings.",
            "button_label": "Reset",
            "button_color": "red",
            "confirm": {
                "required": True,
                "title": "Reset PWS settings?",
                "message": (
                    "This stops the renderer and restores every setting to its "
                    "default, including the API key."
                ),
            },
        },
    ]

    # -- construction -----------------------------------------------------

    def __init__(self) -> None:
        self._base_dir = Path(__file__).resolve().parent
        self._plugin_key = self._base_dir.name.replace(" ", "_").lower()
        self._log_path = self._base_dir / "pws.log"
        self._log_max_bytes = 5 * 1024 * 1024
        self._start_lock_path = self._base_dir / ".start.lock"

        # Station N listens on _BASE_PORT + (N - 1); distinct from other
        # weather plugins, which commonly sit at 5950+.
        self._station_count = _STATION_COUNT
        # Channel artwork. Dispatcharr stores a URL, so this only resolves if
        # the plugin folder is reachable over HTTP; harmless when it is not.
        self._logo_url = f"http://127.0.0.1:{_BASE_PORT}/logo.png"

        self._channel_group_name = "Weather"
        self._channel_title = "PWS Weather"
        self._stream_title = "PWS Feed"
        self._stream_profile_id: Optional[int] = None

        self._output_defaults = {"fps": 30, "width": 1920, "height": 1080,
                                 "video_kbps": 3500}
        self._field_defaults = {f["id"]: f.get("default") for f in self.fields}

    # -- entry point ------------------------------------------------------

    def run(self, action: str, params: Dict[str, Any],
            context: Dict[str, Any]) -> Dict[str, Any]:
        action = (action or "").lower()
        context = self._context_with_params(context, params)

        if action in {"", "status"}:
            response = self._handle_status(context)
        elif action == "start":
            response = self._handle_start(context)
        elif action == "stop":
            response = self._handle_stop(context)
        elif action == "reset_defaults":
            response = self._handle_reset_defaults(context)
        else:
            response = {"status": "error", "message": f"Unknown action '{action}'"}

        return self._finalize_response(response, context)

    def stop(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Called by Dispatcharr when the plugin is disabled; stops every station."""
        if not context or "settings" not in context:
            try:
                cfg = PluginConfig.objects.get(key=self._plugin_key)
                settings = dict(cfg.settings or {})
            except PluginConfig.DoesNotExist:
                settings = {}
            context = {"settings": settings, "logger": None}
        return self._handle_stop(context)

    # -- actions ----------------------------------------------------------

    def _handle_start(self, context: Dict[str, Any]) -> Dict[str, Any]:
        logger = context.get("logger")
        settings = dict(context.get("settings") or {})

        api_key = (settings.get("api_key") or "").strip()
        if not api_key:
            return {
                "status": "error",
                "message": "A Pirate Weather API key is required. Get one free at "
                           "pirateweather.net and subscribe to the Forecast API.",
                "settings": settings,
            }

        wanted = self._configured_stations(settings)
        if not wanted:
            enabled = [i for i in self._station_indices()
                       if self._station_enabled(settings, i)]
            msg = ("Enter a valid 5-digit ZIP code for at least one station."
                   if enabled else "Enable at least one station and give it a ZIP code.")
            return {"status": "error", "message": msg, "settings": settings}

        desired = self._resolve_output_settings(settings)
        data_interval, regional_interval = self._refresh_intervals(len(wanted))

        updates: Dict[str, Any] = {}
        clears: list[str] = []
        started: list[str] = []
        errors: list[str] = []

        with self._start_guard():
            # Stop any station that is running but no longer wanted.
            for idx in self._station_indices():
                if idx in wanted:
                    continue
                pid = self._station_runtime(settings, idx, "pid")
                token = self._station_runtime(settings, idx, "run_token")
                if pid and self._is_process_running(pid, token):
                    self._terminate_process(pid, logger, expected_token=token)
                    if logger:
                        logger.info("PWS station %s stopped (no longer enabled)", idx)
                if pid:
                    clears.extend([_station_runtime_key(idx, "pid"),
                                   _station_runtime_key(idx, "run_token")])
                updates[_station_runtime_key(idx, "running")] = False

            for idx in wanted:
                result = self._start_station(
                    idx, settings, api_key, desired,
                    data_interval, regional_interval, logger,
                )
                if result.get("error"):
                    errors.append(f"Station {idx}: {result['error']}")
                    continue
                if result.get("updates"):
                    updates.update(result["updates"])
                if result.get("clears"):
                    clears.extend(result["clears"])
                if result.get("label"):
                    started.append(result["label"])

            persisted = self._persist_settings(updates, clear=clears)

        if not started:
            return {
                "status": "error",
                "message": "; ".join(errors) or "No stations could be started.",
                "settings": persisted,
            }

        message = f"PWS started {len(started)} station(s): " + "; ".join(started)
        if len(wanted) > 1:
            message += (f". Forecast refresh is every {data_interval // 60} min per "
                        f"station to stay inside the API quota.")
        if errors:
            message += " Problems: " + "; ".join(errors)
        return {"status": "running", "message": message, "settings": persisted}

    def _start_station(self, idx: int, settings: Dict[str, Any], api_key: str,
                       desired: Dict[str, Any], data_interval: int,
                       regional_interval: int, logger: Any) -> Dict[str, Any]:
        """Start one station. Returns updates/clears, or an error string."""
        updates: Dict[str, Any] = {}
        clears: list[str] = []
        rk = lambda name: _station_runtime_key(idx, name)

        zip_code = self._station_zip(settings, idx)
        stream_url = self._station_stream_url(idx)
        port = self._station_port(idx)

        pid = self._station_runtime(settings, idx, "pid")
        run_token = self._station_runtime(settings, idx, "run_token")

        if pid and self._is_process_running(pid, run_token):
            current = self._station_runtime(settings, idx, "encoding") or {}
            changed = any(current.get(k) != desired.get(k)
                          for k in ("fps", "width", "height", "video_kbps"))
            if not changed:
                updates[rk("output_url")] = stream_url
                updates[rk("running")] = True
                label = (self._station_runtime(settings, idx, "location_label")
                         or zip_code)
                return {"updates": updates, "clears": clears,
                        "label": f"{label} (already running)"}
            if logger:
                logger.info("Station %s output changed; restarting", idx)
            self._terminate_process(pid, logger, expected_token=run_token)
            clears.extend([rk("pid"), rk("run_token")])
            pid = None

        if pid and not self._is_process_running(pid, run_token):
            clears.extend([rk("pid"), rk("run_token")])

        if not self._is_port_available(port):
            return {"error": f"port {port} is already in use"}

        location_label = (
            str(self._station_setting(settings, idx, "location_name") or "").strip()
            or self._resolve_location(zip_code) or ""
        )

        try:
            stream, channel = self._ensure_stream_and_channel(
                settings, idx, location_label, stream_url
            )
        except Exception as exc:
            if logger:
                logger.exception("Station %s: channel setup failed", idx)
            return {"error": f"channel setup failed ({exc})"}

        token = uuid.uuid4().hex
        try:
            pid = self._launch_process(
                idx, api_key, zip_code, location_label, desired, settings,
                token, stream_url, data_interval, regional_interval, logger,
            )
        except Exception as exc:
            if logger:
                logger.exception("Station %s: launch failed", idx)
            return {"error": f"launch failed ({exc})"}

        updates.update({
            rk("pid"): pid,
            rk("run_token"): token,
            rk("pid_started_at"): time.time(),
            rk("running"): True,
            rk("last_started_at"): timezone.now().isoformat(),
            rk("stream_id"): stream.id,
            rk("channel_id"): channel.id,
            rk("resolved_channel_number"): channel.channel_number,
            rk("location_label"): location_label,
            rk("output_url"): stream_url,
            rk("encoding"): desired,
        })
        label = location_label or zip_code
        return {"updates": updates, "clears": clears,
                "label": f"{label} on ch {channel.channel_number}"}

    def _handle_stop(self, context: Dict[str, Any]) -> Dict[str, Any]:
        logger = context.get("logger")
        settings = dict(context.get("settings") or {})

        updates: Dict[str, Any] = {}
        clears: list[str] = []
        stopped = 0

        for idx in self._station_indices():
            rk = lambda name: _station_runtime_key(idx, name)
            pid = self._station_runtime(settings, idx, "pid")
            token = self._station_runtime(settings, idx, "run_token")
            if pid and self._terminate_process(pid, logger, expected_token=token):
                stopped += 1
                updates[rk("last_stopped_at")] = timezone.now().isoformat()
            if pid:
                clears.append(rk("pid"))
            if token:
                clears.append(rk("run_token"))
            updates[rk("running")] = False

        persisted = self._persist_settings(updates, clear=clears)
        return {
            "status": "stopped",
            "message": (f"PWS stopped {stopped} station(s)." if stopped
                        else "PWS is not running."),
            "settings": persisted,
        }

    def _handle_status(self, context: Dict[str, Any]) -> Dict[str, Any]:
        settings = dict(context.get("settings") or {})
        running, settings = self._refresh_running_state(settings)
        if not running:
            return {"status": "stopped", "message": "PWS is stopped.",
                    "settings": settings}

        parts = []
        for idx in self._station_indices():
            if not self._is_process_running(
                self._station_runtime(settings, idx, "pid"),
                self._station_runtime(settings, idx, "run_token"),
            ):
                continue
            label = (self._station_runtime(settings, idx, "location_label")
                     or self._station_zip(settings, idx) or f"station {idx}")
            number = self._station_runtime(settings, idx, "resolved_channel_number")
            parts.append(f"{label} (ch {number})" if number else str(label))
        return {
            "status": "running",
            "message": "PWS is running: " + ", ".join(parts),
            "settings": settings,
        }

    def _handle_reset_defaults(self, context: Dict[str, Any]) -> Dict[str, Any]:
        logger = context.get("logger")
        settings = dict(context.get("settings") or {})
        running, settings = self._refresh_running_state(settings)
        if running:
            stop_context = dict(context)
            stop_context["settings"] = settings
            settings = dict(self._handle_stop(stop_context).get("settings") or {})

        defaults = {f["id"]: f.get("default") for f in self.fields}
        clears = []
        for idx in self._station_indices():
            for name in _RUNTIME_FIELDS:
                key = _station_runtime_key(idx, name)
                if key not in defaults:
                    clears.append(key)
            defaults[_station_runtime_key(idx, "running")] = False
        persisted = self._persist_settings(defaults, clear=clears)
        if logger:
            logger.info("PWS settings reset to defaults.")
        return {
            "status": "stopped",
            "message": "PWS settings restored to defaults.",
            "settings": persisted,
        }

    # -- response shaping -------------------------------------------------

    def _finalize_response(self, response: Dict[str, Any],
                           context: Dict[str, Any]) -> Dict[str, Any]:
        response = dict(response or {})
        response_settings = response.get("settings")
        base = dict(response_settings) if isinstance(response_settings, dict) \
            else dict(context.get("settings") or {})
        running, latest = self._refresh_running_state(base)

        response["actions"] = [
            {
                "id": a.get("id"),
                "label": a.get("label"),
                "description": a.get("description"),
                **({"confirm": a["confirm"]} if a.get("confirm") else {}),
            }
            for a in self.actions
        ]
        response["settings"] = latest
        if response.get("status") not in {"running", "stopped", "error"}:
            response["status"] = "running" if running else "stopped"
        return response

    def _refresh_running_state(
        self, settings: Dict[str, Any]
    ) -> tuple[bool, Dict[str, Any]]:
        """True if any station is alive; prunes stale PIDs for all of them."""
        current = dict(settings or {})
        updates: Dict[str, Any] = {}
        clears: list[str] = []
        any_running = False

        for idx in self._station_indices():
            rk = lambda name: _station_runtime_key(idx, name)
            pid = current.get(rk("pid"))
            token = current.get(rk("run_token"))
            alive = self._is_process_running(pid, token)
            if alive:
                any_running = True
                if not current.get(rk("running")):
                    updates[rk("running")] = True
                expected = self._station_stream_url(idx)
                if current.get(rk("output_url")) != expected:
                    updates[rk("output_url")] = expected
            else:
                if current.get(rk("running")):
                    updates[rk("running")] = False
                if pid:
                    clears.append(rk("pid"))
                if token:
                    clears.append(rk("run_token"))

        if updates or clears:
            current = self._persist_settings(updates, clear=clears)
        return any_running, current

    # -- settings plumbing ------------------------------------------------

    def _context_with_params(self, context: Dict[str, Any],
                             params: Dict[str, Any]) -> Dict[str, Any]:
        base = dict(context or {})
        stored = dict(base.get("settings") or {})
        updates: Dict[str, Any] = {}
        if params:
            for field in self.fields:
                fid = field["id"]
                if fid in params:
                    stored[fid] = params[fid]
                    updates[fid] = params[fid]
        if updates:
            stored = dict(self._persist_settings(updates))
        base["settings"] = stored
        return base

    # -- station helpers ---------------------------------------------------

    def _station_indices(self) -> list[int]:
        return list(range(1, self._station_count + 1))

    def _station_port(self, idx: int) -> int:
        return _BASE_PORT + (idx - 1)

    def _station_stream_url(self, idx: int) -> str:
        suffix = "" if idx == 1 else f"_{idx}"
        return f"http://127.0.0.1:{self._station_port(idx)}/pws{suffix}.ts"

    def _station_setting(self, settings: Dict[str, Any], idx: int,
                         field: str) -> Any:
        key = _station_field_id(idx, field)
        if key in settings:
            return settings.get(key)
        return self._field_defaults.get(key)

    def _station_enabled(self, settings: Dict[str, Any], idx: int) -> bool:
        raw = self._station_setting(settings, idx, "enabled")
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)

    def _station_zip(self, settings: Dict[str, Any], idx: int) -> str:
        return str(self._station_setting(settings, idx, "zip_code") or "").strip()

    def _configured_stations(self, settings: Dict[str, Any]) -> list[int]:
        """Enabled stations that also have a usable ZIP."""
        out = []
        for idx in self._station_indices():
            if not self._station_enabled(settings, idx):
                continue
            zip_code = self._station_zip(settings, idx)
            if zip_code.isdigit() and len(zip_code) == 5:
                out.append(idx)
        return out

    def _station_runtime(self, settings: Dict[str, Any], idx: int,
                         field: str) -> Any:
        return settings.get(_station_runtime_key(idx, field))

    def _refresh_intervals(self, station_count: int) -> tuple[int, int]:
        """
        Per-station refresh intervals, scaled by how many stations are running.

        Every station polls Pirate Weather independently, so running three at
        the single-station cadence would triple the monthly call count and blow
        straight through the free tier. Spreading the intervals keeps the total
        flat at roughly 7,200 calls/month however many stations are enabled.
        """
        n = max(1, int(station_count))
        return 600 * n, 5400 * n

    def _allowed_setting_keys(self) -> set[str]:
        keys = {f["id"] for f in self.fields}
        for idx in self._station_indices():
            for name in _RUNTIME_FIELDS:
                keys.add(_station_runtime_key(idx, name))
        return keys

    def _persist_settings(self, updates: Dict[str, Any],
                          clear: Optional[list[str]] = None) -> Dict[str, Any]:
        clear = clear or []
        allowed = self._allowed_setting_keys()
        with transaction.atomic():
            cfg = PluginConfig.objects.select_for_update().get(key=self._plugin_key)
            stored = dict(cfg.settings or {})
            stored.update(updates)
            for key in clear:
                stored.pop(key, None)
            stored = {k: v for k, v in stored.items() if k in allowed}
            cfg.settings = stored
            cfg.save(update_fields=["settings", "updated_at"])
            return stored

    # -- helpers ----------------------------------------------------------

    @contextmanager
    def _start_guard(self):
        with _START_LOCK:
            lock_file = None
            try:
                if fcntl:
                    lock_file = open(self._start_lock_path, "a+b")
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                if lock_file and fcntl:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
                    lock_file.close()

    def _is_port_available(self, port: int, host: str = "127.0.0.1") -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, int(port)))
            return True
        except OSError:
            return False
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _resolve_location(self, zip_code: str) -> Optional[str]:
        if resolve_zip is None:
            return None
        try:
            data = resolve_zip(zip_code)
        except Exception:
            return None
        if not data:
            return None
        city = (data.get("city") or "").strip()
        state = (data.get("state") or "").strip()
        if city and state:
            return f"{city}, {state}"
        return city or state or None

    def _resolve_output_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        width = self._output_defaults["width"]
        height = self._output_defaults["height"]
        raw = (settings.get("resolution") or "").strip().lower()
        if raw:
            try:
                parts = raw.split("x", 1)
                if len(parts) == 2:
                    w, h = int(parts[0]), int(parts[1])
                    if w > 0 and h > 0:
                        width, height = w, h
            except (TypeError, ValueError):
                pass

        video_kbps = self._output_defaults["video_kbps"]
        try:
            value = settings.get("video_kbps")
            if value not in (None, ""):
                video_kbps = max(500, min(20000, int(value)))
        except (TypeError, ValueError):
            pass

        return {
            "fps": self._output_defaults["fps"],
            "width": width,
            "height": height,
            "video_kbps": video_kbps,
        }

    @staticmethod
    def _music_volume(settings: Dict[str, Any]) -> float:
        """UI percentage (0-100) to an ffmpeg gain (0.0-1.0)."""
        try:
            value = settings.get("music_volume")
            if value in (None, ""):
                return 0.5
            return max(0.0, min(1.0, float(value) / 100.0))
        except (TypeError, ValueError):
            return 0.5

    def _sanitize_rss_urls(self, raw: str) -> list[str]:
        if not raw:
            return []
        normalized = raw.replace("\r", "\n").replace(";", ",").replace("\n", ",")
        urls: list[str] = []
        for item in normalized.split(","):
            candidate = item.strip()
            if not candidate or len(candidate) > 500:
                continue
            if urlparse(candidate).scheme not in {"http", "https"}:
                continue
            urls.append(candidate)
            if len(urls) >= 10:
                break
        return urls

    # -- channel / stream -------------------------------------------------

    def _get_stream_profile_id(self) -> int:
        if self._stream_profile_id is not None:
            return self._stream_profile_id
        profile = (
            StreamProfile.objects.filter(name__iexact="proxy").first()
            or StreamProfile.objects.filter(name__icontains="proxy").first()
            or StreamProfile.objects.first()
        )
        if not profile:
            raise RuntimeError(
                "No stream profiles found. Create one (recommended name: 'proxy')."
            )
        self._stream_profile_id = profile.id
        return self._stream_profile_id

    def _ensure_stream_and_channel(self, settings: Dict[str, Any], idx: int,
                                   location_label: str,
                                   stream_url: str) -> tuple[Stream, Channel]:
        suffix = location_label or f"Station {idx}"
        stream_name = f"{self._stream_title} ({suffix})"
        channel_name = f"{self._channel_title} - {suffix}"

        stream = self._get_or_create_stream(
            stream_name, self._station_runtime(settings, idx, "stream_id"), stream_url
        )
        channel = self._get_or_create_channel(
            channel_name, self._station_runtime(settings, idx, "channel_id"),
            self._preferred_channel_number(settings, idx),
        )
        ChannelStream.objects.get_or_create(channel=channel, stream=stream,
                                            defaults={"order": 0})
        return stream, channel

    def _preferred_channel_number(self, settings: Dict[str, Any],
                                  idx: int) -> Optional[int]:
        raw = self._station_setting(settings, idx, "channel_number")
        if raw in (None, ""):
            return None
        try:
            number = int(raw)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _get_or_create_stream(self, name: str, stream_id: Optional[int],
                              stream_url: str) -> Stream:
        if stream_id:
            try:
                return Stream.objects.get(id=stream_id)
            except Stream.DoesNotExist:
                pass
        existing = Stream.objects.filter(name=name, url=stream_url).first()
        if existing:
            return existing
        return Stream.objects.create(
            name=name,
            url=stream_url,
            logo_url=self._logo_url,
            tvg_id=None,
            stream_profile_id=self._get_stream_profile_id(),
        )

    def _get_or_create_channel(self, name: str, channel_id: Optional[int],
                               preferred_number: Optional[int]) -> Channel:
        if channel_id:
            try:
                return Channel.objects.get(id=channel_id)
            except Channel.DoesNotExist:
                pass

        if preferred_number:
            match = Channel.objects.filter(
                channel_number=preferred_number,
                channel_group__name=self._channel_group_name,
            ).first()
            if match:
                if match.name.startswith(self._channel_title):
                    return match
                raise RuntimeError(
                    f"Channel number {preferred_number} is already used by "
                    f"'{match.name}' in the {self._channel_group_name} group."
                )

        group, _ = ChannelGroup.objects.get_or_create(name=self._channel_group_name)
        number = preferred_number or Channel.get_next_available_channel_number(
            starting_from=1000
        )
        return Channel.objects.create(
            name=name,
            channel_number=number,
            channel_group=group,
            stream_profile_id=self._get_stream_profile_id(),
        )

    # -- process management -----------------------------------------------

    def _python_interpreter(self) -> str:
        """Find a real interpreter even when Dispatcharr runs under uWSGI."""
        exe = Path(sys.executable or "")
        candidates: list[Path] = []
        if exe.name and exe.name.lower().startswith("uwsgi"):
            candidates.extend([exe.with_name("python"), exe.with_name("python3")])
        venv = os.environ.get("VIRTUAL_ENV")
        if venv:
            candidates.extend([Path(venv) / "bin" / "python",
                               Path(venv) / "bin" / "python3"])
        candidates.extend([exe, Path("python3"), Path("python")])

        for candidate in candidates:
            if not candidate:
                continue
            if candidate.is_absolute() and candidate.exists():
                return str(candidate)
            resolved = shutil.which(str(candidate))
            if resolved:
                return resolved
        raise RuntimeError("Unable to locate a Python interpreter for PWS")

    def _rotate_log_if_needed(self) -> None:
        try:
            if self._log_path.exists() and \
                    self._log_path.stat().st_size > self._log_max_bytes:
                backup = self._log_path.with_suffix(self._log_path.suffix + ".1")
                if backup.exists():
                    backup.unlink()
                self._log_path.rename(backup)
        except Exception:
            pass

    def _launch_process(self, idx: int, api_key: str, zip_code: str,
                        location_label: str, encoding: Dict[str, Any],
                        settings: Dict[str, Any], run_token: str,
                        stream_url: str, data_interval: int,
                        regional_interval: int, logger: Any) -> int:
        cmd = [
            self._python_interpreter(), "-m", "pws.main",
            "--zip", zip_code,
            "--units", (settings.get("units") or "us"),
            "--radar-source", (settings.get("radar_source") or "noaa"),
            "--music-volume", f"{self._music_volume(settings):.2f}",
            "--data-interval-sec", str(int(data_interval)),
            "--regional-interval-sec", str(int(regional_interval)),
            "--output-fps", str(encoding["fps"]),
            "--w", str(encoding["width"]),
            "--h", str(encoding["height"]),
            "--video-kbps", str(encoding["video_kbps"]),
            "--out", stream_url,
        ]
        if location_label:
            cmd += ["--location-name", location_label]
        for url in self._sanitize_rss_urls(settings.get("rss_urls") or ""):
            cmd += ["--rss-url", url]

        env = os.environ.copy()
        base = str(self._base_dir)
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            os.pathsep.join([base, existing]) if existing and base not in
            existing.split(os.pathsep) else (existing or base)
        )
        # The key travels through the environment, never argv, so it cannot leak
        # into `ps` output or the plugin log header.
        env["PIRATE_WEATHER_API_KEY"] = api_key
        env["PWS_PLUGIN_KEY"] = self._plugin_key
        env["PWS_RUN_TOKEN"] = run_token
        env["PWS_STATION_INDEX"] = str(idx)
        env.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate_log_if_needed()
        header = (f"\n--- [{datetime.now().isoformat()}] Starting PWS station "
                  f"{idx} for ZIP {zip_code} ---\n")
        with open(self._log_path, "ab") as fh:
            fh.write(header.encode("utf-8"))

        log_handle = open(self._log_path, "ab", buffering=0)
        popen_kwargs: Dict[str, Any] = {
            "cwd": str(self._base_dir),
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "env": env,
        }
        if os.name != "nt":
            popen_kwargs["preexec_fn"] = os.setsid
        else:  # pragma: no cover - Windows
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            proc = subprocess.Popen(cmd, **popen_kwargs)
        finally:
            log_handle.close()

        if logger:
            logger.info("PWS station %s started with PID %s", idx, proc.pid)
        return proc.pid

    def _terminate_process(self, pid: int, logger: Any,
                           expected_token: Optional[str] = None) -> bool:
        if not self._is_process_running(pid, expected_token):
            return False

        def kill(target: int, sig: int) -> None:
            if os.name != "nt" and hasattr(os, "killpg"):
                os.killpg(target, sig)
            else:
                os.kill(target, sig)

        try:
            kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        except Exception:
            if logger:
                logger.exception("Failed to terminate PWS PID %s", pid)
            raise

        deadline = time.time() + 10
        while time.time() < deadline:
            if not self._is_process_running(pid):
                break
            time.sleep(0.5)
        else:
            try:
                kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        self._reap_process(pid)
        if logger:
            logger.info("PWS PID %s terminated", pid)
        return True

    def _is_process_running(self, pid: Optional[int],
                            expected_token: Optional[str] = None) -> bool:
        if not pid:
            return False
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            return False

        if expected_token and not self._pid_matches_token(pid_int, expected_token):
            return False

        try:
            finished, _ = os.waitpid(pid_int, os.WNOHANG)
            if finished == pid_int:
                return False
        except ChildProcessError:
            pass
        except OSError:
            return False

        try:
            os.kill(pid_int, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _reap_process(self, pid: int) -> None:
        try:
            while True:
                finished, _ = os.waitpid(pid, os.WNOHANG)
                if finished in (0, pid):
                    break
        except (ChildProcessError, OSError):
            pass

    def _pid_matches_token(self, pid: int, expected_token: str) -> bool:
        """Guard against acting on a recycled PID."""
        token = self._read_proc_env_token(pid)
        if token:
            return token == expected_token
        cmdline = self._read_proc_cmdline(pid)
        if cmdline:
            # Fall back to a shape check when /proc/<pid>/environ is unreadable.
            return "pws.main" in cmdline and "--out" in cmdline
        return False

    def _read_proc_env_token(self, pid: int) -> Optional[str]:
        try:
            with open(f"/proc/{pid}/environ", "rb") as fh:
                entries = fh.read().split(b"\0")
        except Exception:
            return None
        for entry in entries:
            if entry.startswith(b"PWS_RUN_TOKEN="):
                return entry.split(b"=", 1)[1].decode("utf-8", "ignore")
        return None

    def _read_proc_cmdline(self, pid: int) -> Optional[str]:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw = fh.read().replace(b"\0", b" ").decode("utf-8", "ignore")
        except Exception:
            return None
        return raw.strip() or None
