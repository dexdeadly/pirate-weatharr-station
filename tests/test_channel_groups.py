"""Stations grouped onto shared channels (one renderer showing several locations)."""
import json

from pws import status

THREE = {
    "api_key": "KEY", "units": "us",
    "station_1_enabled": True, "zip_code": "77002",                        # Houston
    "station_2_enabled": True, "station_2_zip_code": "78701",              # Austin
    "station_3_enabled": True, "station_3_lat": "39.74", "station_3_lon": "-104.99",
    "station_3_location_name": "Denver",
}


def start(p, env, params=None):
    cfg = env.db["pirate_weatharr_station"]
    return p.run("start", params or {}, {"settings": dict(cfg.settings), "logger": None})


def launched(env):
    """[(lead station, [location names])] for every launch so far."""
    return [(idx, [loc["name"] for loc in locs]) for idx, _pid, _s, locs, _l, _di in env.launches]


def test_default_is_one_channel_per_station(plugin_env):
    p = plugin_env.make(dict(THREE))
    r = start(p, plugin_env)
    assert "3 channel(s)" in r["message"]
    names = launched(plugin_env)
    assert [lead for lead, _ in names] == [1, 2, 3]
    assert all(len(locs) == 1 for _, locs in names)


def test_all_on_one_channel(plugin_env):
    p = plugin_env.make({**THREE, "channel": "A", "station_2_channel": "A", "station_3_channel": "A"})
    r = start(p, plugin_env)
    assert "1 channel(s)" in r["message"]
    (lead, locs), = launched(plugin_env)
    assert lead == 1 and len(locs) == 3 and locs[2] == "Denver"
    label = plugin_env.launches[0][4]
    assert " · " in label and label.endswith("Denver")
    # Quota: refresh still scales with three locations, not one channel.
    assert plugin_env.launches[0][5] == 3 * 10 * 60


def test_two_plus_one(plugin_env):
    p = plugin_env.make({**THREE, "station_2_channel": "A", "station_3_channel": "B"})
    start(p, plugin_env)
    groups = launched(plugin_env)
    assert [lead for lead, _ in groups] == [1, 3]
    assert len(groups[0][1]) == 2 and groups[1][1] == ["Denver"]


def test_regrouping_a_running_setup(plugin_env):
    p = plugin_env.make(dict(THREE))
    start(p, plugin_env)
    pids = {idx: pid for idx, pid, *_ in plugin_env.launches}
    r = start(p, plugin_env, {"station_2_channel": "A"})          # merge 2 into 1's channel
    s = plugin_env.db["pirate_weatharr_station"].settings
    assert not p._is_process_running(pids[2], None)              # station 2's channel stopped
    assert "Station 2 now shares Channel A" in r["message"] and "1002" in r["message"]
    assert s["pid"] != pids[1]                                   # channel A relaunched with both
    lead, locs = launched(plugin_env)[-1]
    assert lead == 1 and len(locs) == 2
    assert s.get("station_3_pid") == pids[3]                      # untouched channel keeps running


def test_disabled_station_leaves_its_group(plugin_env):
    p = plugin_env.make({**THREE, "station_2_channel": "A", "station_3_enabled": False})
    start(p, plugin_env)
    (lead, locs), = launched(plugin_env)
    assert lead == 1 and len(locs) == 2


def test_health_lists_each_location(plugin_env):
    p = plugin_env.make(dict(THREE))
    board = status.StatusBoard(status.status_path(p._base_dir, 1))
    import time
    board.update("Houston, TX", {"updated_at": time.time() - 300, "quota_remaining": 9000, "quota_limit": 10000})
    board.update("Austin, TX", {"updated_at": None, "error": "API key rejected (HTTP 401)"})
    line = p._station_health(1)
    assert "Houston, TX: forecast updated 5 min ago" in line
    assert "Austin, TX: problem: API key rejected" in line
    assert line.endswith("(9,000/10,000 API calls left this month)")
    assert json.loads(status.status_path(p._base_dir, 1).read_text())["locations"][1]["location"] == "Austin, TX"
