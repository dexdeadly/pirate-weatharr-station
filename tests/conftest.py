"""
Shared fixtures. Everything runs offline: Dispatcharr/Django are stubbed with
an in-memory PluginConfig table, and tests that touch HTTP mock it.
"""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


class FakeConfig:
    def __init__(self, key: str, settings: dict | None = None, enabled: bool = True):
        self.key, self.settings, self.enabled = key, settings or {}, enabled

    def save(self, update_fields=None):
        pass


class _Query:
    def __init__(self, obj):
        self._obj = obj

    def first(self):
        return self._obj


class _Atomic:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_django_stubs(db: dict) -> None:
    class DoesNotExist(Exception):
        pass

    class Manager:
        def get(self, key):
            if key not in db:
                raise DoesNotExist(key)
            return db[key]

        def filter(self, key):
            return _Query(db.get(key))

        def select_for_update(self):
            return self

    plugin_config = type("PluginConfig", (), {"objects": Manager(), "DoesNotExist": DoesNotExist})
    names = ["django", "django.db", "django.utils", "apps", "apps.channels",
             "apps.channels.models", "apps.plugins", "apps.plugins.models",
             "core", "core.models"]
    mods = {n: types.ModuleType(n) for n in names}
    mods["django.db"].transaction = types.SimpleNamespace(atomic=lambda: _Atomic())
    mods["django.db"].close_old_connections = lambda: None
    import datetime as _dt
    mods["django.utils"].timezone = types.SimpleNamespace(now=lambda: _dt.datetime.now())
    for n in ["Channel", "ChannelGroup", "ChannelStream", "Logo", "Stream"]:
        setattr(mods["apps.channels.models"], n, object)
    mods["apps.plugins.models"].PluginConfig = plugin_config
    mods["core.models"].StreamProfile = object
    sys.modules.update(mods)


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """
    Import plugin.py as Dispatcharr would (a package named after the install
    folder) with Django stubbed. Renderer launches are replaced by a harmless
    sleeper process carrying the run token, so process checks behave for real.
    Returns a namespace: module, db, make(), launches, created_channels.
    """
    db: dict[str, FakeConfig] = {}
    _install_django_stubs(db)

    install = tmp_path / "pirate_weatharr_station"
    install.mkdir()
    (install / "plugin.py").write_text((REPO / "plugin.py").read_text())
    os.symlink(REPO / "pws", install / "pws")

    pkg_name = f"plugpkg_{tmp_path.name}"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(install)]
    sys.modules[pkg_name] = pkg
    spec = importlib.util.spec_from_file_location(f"{pkg_name}.plugin", install / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{pkg_name}.plugin"] = module
    spec.loader.exec_module(module)

    module._AUTOSTART_SCHEDULED = True   # tests call _autostart() directly
    module._BASE_PORT = 48960 + (os.getpid() % 500) * 3

    procs: list[subprocess.Popen] = []
    launches: list[tuple] = []
    created: list[int] = []

    def fake_launch(self, idx, api_key, zip_code, coords, label, encoding, settings,
                    token, url, di, ri, logger):
        # Same argv shape as a real renderer ("pws.main ... --out"): the plugin
        # falls back to that shape check when environ is momentarily unreadable.
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)",
                              "pws.main", "--out", url],
                             env=dict(os.environ, PWS_RUN_TOKEN=token),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        procs.append(p)
        launches.append((idx, p.pid, dict(settings)))
        return p.pid

    def fake_ensure(self, settings, idx, label, url, fallback):
        sid = self._station_runtime(settings, idx, "stream_id")
        cid = self._station_runtime(settings, idx, "channel_id")
        if not sid:
            created.append(idx)
        ns = types.SimpleNamespace
        return ns(id=sid or 900 + idx), ns(id=cid or 800 + idx, channel_number=1000 + idx)

    monkeypatch.setattr(module.Plugin, "_launch_process", fake_launch)
    monkeypatch.setattr(module.Plugin, "_ensure_stream_and_channel", fake_ensure)

    def make(settings: dict | None = None):
        db.setdefault("pirate_weatharr_station", FakeConfig("pirate_weatharr_station", settings or {}))
        return module.Plugin()

    env = types.SimpleNamespace(module=module, db=db, make=make, launches=launches,
                                created_channels=created, procs=procs,
                                FakeConfig=FakeConfig, install=install)
    yield env
    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass
    for key in [k for k in sys.modules if k.startswith(pkg_name)]:
        sys.modules.pop(key, None)
