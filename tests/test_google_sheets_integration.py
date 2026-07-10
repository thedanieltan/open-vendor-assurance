"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_human_browser_artifact_contains_resolvable_adp_sources(tmp_path: Path) -> None:
    site_out = tmp_path / "site"
    subprocess.run(
        [sys.executable, "site/build.py", "--out", str(site_out)],
        check=True,
        text=True,
    )

    vendor_search = json.loads((site_out / "data/vendor-search.min.json").read_text(encoding="utf-8"))
    assert isinstance(vendor_search, dict)
    assert isinstance(vendor_search.get("items"), list)
    adp = next(vendor for vendor in vendor_search["items"] if vendor["vendor_id"] == "adp")
    assert adp["official_domains"][0] == "adp.com"
    assert adp["detail_path"]

    detail_path = site_out / adp["detail_path"]
    assert detail_path.is_file(), adp
    detail = json.loads(detail_path.read_text(encoding="utf-8"))
    sources = detail.get("sources", [])
    assert any(source.get("source_type") == "dpa" and source.get("source_url", "").startswith("https://") for source in sources)
