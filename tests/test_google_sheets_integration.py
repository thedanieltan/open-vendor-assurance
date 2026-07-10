"""Temporary browser-local human-user smoke; this branch is never merged."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_human_browser_artifact_contains_adp_source_shard(tmp_path: Path) -> None:
    site_out = tmp_path / "site"
    subprocess.run(
        [sys.executable, "site/build.py", "--out", str(site_out)],
        check=True,
        text=True,
    )

    vendor_search = json.loads((site_out / "data/vendor-search.min.json").read_text(encoding="utf-8"))
    adp = next(vendor for vendor in vendor_search["items"] if vendor["vendor_id"] == "adp")
    assert adp["official_domains"][0] == "adp.com"
    assert adp["detail_path"] == "data/vendors/adp.json"

    detail = json.loads((site_out / adp["detail_path"]).read_text(encoding="utf-8"))
    assert detail["vendor"]["vendor_id"] == "adp"
    assert any(
        source.get("source_type") == "dpa" and source.get("source_url", "").startswith("https://")
        for source in detail["source_records"]
    )
