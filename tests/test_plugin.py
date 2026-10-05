"""Plugin lifecycle: start/restart-on-change, auto-start, legacy 'pws' migration."""
import os
import signal
import subprocess
import sys
import threading
import time

BASE = {"api_key": "KEY", "zip_code": "77002", "station_1_enabled": True, "units": "us"}


def run(p, env, action, params=None):
    cfg = env.db["pirate_weatharr_station"]
    return p.run(action, params or {}, {"settings": dict(cfg.settings), "logger": None})


def settings(env):
    return env.db["pirate_weatharr_station"].settings


def alive(p, pid):
    return p._is_process_running(pid, None)


def kill(pid):
    os.killpg(pid, signal.SIGKILL)
    time.sleep(0.3)


def test_start_restart_on_change_and_restart_action(plugin_env):
    p = plugin_env.make(dict(BASE))
    assert run(p, plugin_env, "start")["status"] == "running"
    pid1 = settings(plugin_env)["pid"]
    assert alive(p, pid1) and settings(plugin_env)["desired_running"] is True

    run(p, plugin_env, "start")                        # nothing changed
    assert settings(plugin_env)["pid"] == pid1 and len(plugin_env.launches) == 1

    run(p, plugin_env, "start", {"units": "si"})       # setting changed -> relaunch
    pid2 = settings(plugin_env)["pid"]
    assert pid2 != pid1 and alive(p, pid2) and not alive(p, pid1)

    run(p, plugin_env, "restart")
    assert settings(plugin_env)["pid"] not in (None, pid2)


def test_autostart_rules(plugin_env):
    p = plugin_env.make(dict(BASE))
    run(p, plugin_env, "start")
    kill(settings(plugin_env)["pid"])                  # container restart
    n = len(plugin_env.launches)
    p._autostart()
    assert len(plugin_env.launches) == n + 1 and alive(p, settings(plugin_env)["pid"])

    p._autostart()                                     # already running: no-op
    assert len(plugin_env.launches) == n + 1

    run(p, plugin_env, "stop")                         # user Stop: stay off
    assert settings(plugin_env)["desired_running"] is False
    p._autostart()
    assert len(plugin_env.launches) == n + 1


def test_reload_keeps_desired_disable_clears_it(plugin_env):
    p = plugin_env.make(dict(BASE))
    run(p, plugin_env, "start")
    p.stop({"settings": dict(settings(plugin_env)), "reason": "reload"})
    assert settings(plugin_env)["desired_running"] is True
    p.stop({"settings": dict(settings(plugin_env)), "reason": "disable"})
    assert settings(plugin_env)["desired_running"] is False


def test_concurrent_autostarts_launch_once(plugin_env):
    p = plugin_env.make(dict(BASE))
    run(p, plugin_env, "start")
    kill(settings(plugin_env)["pid"])
    n = len(plugin_env.launches)
    threads = [threading.Thread(target=p._autostart) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(plugin_env.launches) == n + 1


def test_migrates_legacy_pws_install(plugin_env):
    old_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                env=dict(os.environ, PWS_RUN_TOKEN="old"),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    plugin_env.procs.append(old_proc)
    plugin_env.db["pws"] = plugin_env.FakeConfig("pws", {
        **BASE, "pid": old_proc.pid, "run_token": "old", "running": True,
        "stream_id": 11, "channel_id": 21, "surf_spot": "29.0, -94.8"})
    p = plugin_env.make({})
    assert p._plugin_key == "pirate_weatharr_station"
    assert p._migrate_legacy_install() is True
    new, old = settings(plugin_env), plugin_env.db["pws"]
    time.sleep(0.3)
    assert new["api_key"] == "KEY" and new["channel_id"] == 21 and new["migrated_from"] == "pws"
    assert "pid" not in new and new["desired_running"] is True
    assert old_proc.poll() is not None and old.enabled is False
    p._autostart()
    assert plugin_env.created_channels == []           # existing channel reused
    assert p._migrate_legacy_install() is False         # once only


def test_migration_leaves_hand_configured_install_alone(plugin_env):
    plugin_env.db["pws"] = plugin_env.FakeConfig("pws", {"api_key": "OLD"})
    p = plugin_env.make({"api_key": "NEW"})
    assert p._migrate_legacy_install() is False
    assert settings(plugin_env)["api_key"] == "NEW" and plugin_env.db["pws"].enabled is True
