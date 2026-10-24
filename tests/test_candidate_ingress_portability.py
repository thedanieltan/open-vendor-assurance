from concurrent.futures import ThreadPoolExecutor
from pathlib import PureWindowsPath
import time

import pytest

from tools.openva import vendor_resolution as vr


def test_candidate_lock_serializes_independent_thread_handles(tmp_path):
    counter = tmp_path / "counter.txt"
    counter.write_text("0")

    def increment(_):
        with vr._FileLock(tmp_path / ".lock"):
            value = int(counter.read_text())
            time.sleep(0.005)
            counter.write_text(str(value + 1))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(8)))
    assert counter.read_text() == "8"
    # The lock is released and can be acquired again.
    with vr._FileLock(tmp_path / ".lock"):
        assert counter.read_text() == "8"


def test_candidate_lock_denies_unsupported_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(vr, "fcntl", None)
    monkeypatch.setattr(vr, "msvcrt", None)
    lock = vr._FileLock(tmp_path / ".lock")
    with pytest.raises(RuntimeError, match="requires filesystem locking"):
        with lock:
            pytest.fail("transaction must never execute without a lock")
    assert lock._handle is None


def test_git_object_paths_use_forward_slashes_on_windows():
    root = PureWindowsPath("D:/registry")
    path = root / "maintenance" / "candidates" / "candidate.json"
    assert vr._rel(path, root) == "maintenance/candidates/candidate.json"
