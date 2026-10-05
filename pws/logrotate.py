"""
Size-based rotation for a station's log while it runs.

The plugin starts each renderer with stdout/stderr pointing at that station's
own log file (pws_station<N>.log). Previously every station appended to one
shared pws.log that was only rotated when a station was launched, so a station
left running for weeks grew it without bound. The renderer now checks the size
once a minute and, past the limit, moves the file to ``.1`` (replacing the
previous backup) and re-points file descriptors 1 and 2 at a fresh file. ffmpeg
inherits fd 2 when it is (re)started, so it follows along on its next restart.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

MAX_BYTES = 5 * 1024 * 1024
CHECK_SEC = 60.0


def rotate_if_needed(path: Path, max_bytes: int = MAX_BYTES) -> bool:
    """Rotate ``path`` if it's over ``max_bytes``. Returns True if it rotated."""
    try:
        if path.stat().st_size <= max_bytes:
            return False
    except OSError:
        return False
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    try:
        os.replace(path, path.with_name(path.name + ".1"))
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    except OSError:
        return False
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)
    print(f"[log] rotated; previous log is {path.name}.1", flush=True)
    return True


def start(path: Optional[str], max_bytes: int = MAX_BYTES,
          interval: float = CHECK_SEC) -> Optional[threading.Thread]:
    """Background size check for ``path`` (no-op when unset)."""
    if not path:
        return None
    log_path = Path(path)

    def loop() -> None:
        stop = threading.Event()
        while not stop.wait(interval):
            rotate_if_needed(log_path, max_bytes)

    thread = threading.Thread(target=loop, name="log-rotate", daemon=True)
    thread.start()
    return thread
