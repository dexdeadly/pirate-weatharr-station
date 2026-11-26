"""The cross-process start lock must never block in flock() (gevent deadlock)."""
import fcntl
import threading
import time


def test_start_guard_never_blocks_in_flock(plugin_env, monkeypatch):
    p = plugin_env.make({})
    calls = []
    real_flock = fcntl.flock

    def spy(fd, op):
        calls.append(op)
        return real_flock(fd, op)

    monkeypatch.setattr(plugin_env.module.fcntl, "flock", spy)
    with p._start_guard():
        pass
    acquires = [op for op in calls if op & fcntl.LOCK_EX]
    assert acquires and all(op & fcntl.LOCK_NB for op in acquires)


def test_start_guard_waits_for_another_holder(plugin_env, monkeypatch):
    monkeypatch.setattr(plugin_env.module, "_START_LOCK_POLL_SEC", 0.01)
    p = plugin_env.make({})
    entered = threading.Event()

    with open(p._start_lock_path, "a+b") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX)

        def worker():
            with p._start_guard():
                entered.set()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        time.sleep(0.1)
        assert not entered.is_set()
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)

    t.join(timeout=5)
    assert entered.is_set()
