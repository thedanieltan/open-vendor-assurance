"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_human_browser_artifact_builds(tmp_path: Path) -> None:
    site_out = tmp_path / "site"
    subprocess.run(
        [sys.executable, "site/build.py", "--out", str(site_out)],
        check=True,
        text=True,
    )
    assert (site_out / "app.js").is_file()
    assert (site_out / "data/vendor-search.min.json").is_file()
    assert (site_out / "data/vendors/adp.json").is_file()
