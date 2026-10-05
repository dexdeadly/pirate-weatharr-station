"""
Per-station status file the plugin reads for its Status action.

Each renderer rewrites ``pws_station<N>.status.json`` next to its log after
every data refresh: when the forecast last updated, the current error if any,
and the Pirate Weather quota. The plugin process can't see inside the
renderer otherwise, so before this Status could only say "running".
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def status_path(plugin_dir: Path, station: int | str) -> Path:
    return Path(plugin_dir) / f"pws_station{station}.status.json"


def write(path: Optional[Path], payload: dict[str, Any]) -> None:
    if path is None:
        return
    data = dict(payload)
    data["written_at"] = time.time()
    try:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)   # atomic: the plugin never reads half a file
    except OSError:
        pass


def read(path: Path) -> Optional[dict[str, Any]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
