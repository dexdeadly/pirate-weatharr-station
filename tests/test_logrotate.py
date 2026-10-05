import os
import stat
import subprocess
import sys

from conftest import REPO


def test_rotation_moves_log_and_new_file_is_owner_only(tmp_path):
    log = tmp_path / "pws_station1.log"
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "from pws import logrotate\n"
        "print('x' * 200, flush=True)\n"
        "assert logrotate.rotate_if_needed(Path(%r), max_bytes=100)\n"
        "print('after', flush=True)\n"
    ) % (str(REPO), str(log))
    with open(log, "ab") as fh:
        subprocess.run([sys.executable, "-c", code], stdout=fh, stderr=fh, check=True)
    assert (tmp_path / "pws_station1.log.1").read_text().startswith("x" * 200)
    assert "after" in log.read_text()
    assert stat.S_IMODE(os.stat(log).st_mode) & 0o077 == 0     # not group/world readable
