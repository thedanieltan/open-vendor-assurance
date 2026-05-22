import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_site_static_build_passes_and_generates_public_data(tmp_path):
    out = tmp_path / "site-dist"
    result = subprocess.run([sys.executable, "site/build.py", "--out", str(out)], cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert (out / "index.html").is_file()
    assert (out / "data" / "catalog-data.json").is_file()
    assert (out / "data" / "observation-feed.json").is_file()
    catalog = json.loads((out / "data" / "catalog-data.json").read_text(encoding="utf-8"))
    assert catalog["meta"]["profileId"] == "openva.public-metadata.v1"
    assert catalog["sources"][0]["record_class"] == "canonical"
    assert catalog["sources"][0]["catalog_tier"] == "human_reviewed"
    feed = json.loads((out / "data" / "observation-feed.json").read_text(encoding="utf-8"))
    assert feed["events"] == []
    assert feed["contract"]["canonical"] is False
    assert feed["contract"]["catalog_tier"] == "observation"


def test_site_selection_is_memory_only():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in [SITE / "src" / "index.html", SITE / "src" / "app.js", SITE / "build.py"])
    assert "const selectedVendors = new Set();" in app
    assert "const selectedSources = new Set();" in app
    assert "localStorage" not in source_text
    assert "sessionStorage" not in source_text
    assert "reviewed_catalog" in app


def test_site_text_preserves_catalog_and_feed_boundary():
    text = "\n".join(path.read_text(encoding="utf-8") for path in [SITE / "src" / "index.html", SITE / "src" / "app.js", SITE / "README.md"])
    for phrase in [
        "Reviewed Catalog",
        "Live Observation Feed",
        "Reviewed catalog snapshot",
        "not a live monitoring feed",
        "No live observation events are available yet.",
        "observation ledger workflow",
    ]:
        assert phrase in text
    assert 'type="file"' not in text


def test_pages_workflow_deploys_site_and_feed_workflow_uploads_feed_artifact_only():
    reviewed = yaml.safe_load((WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8"))
    feed = yaml.safe_load((WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8"))
    assert reviewed["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert feed["permissions"] == {"contents": "read"}
    assert workflow_triggers(reviewed)["push"] == {"tags": ["v*"]}
    assert workflow_triggers(feed)["schedule"][0]["cron"] == "0 3 * * 0"
    assert "workflow_dispatch" in workflow_triggers(feed)
    reviewed_text = (WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8")
    feed_text = (WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8")
    assert "actions/deploy-pages@v4" in reviewed_text
    assert "actions/deploy-pages" not in feed_text
    assert "actions/upload-artifact@v6" in feed_text
    assert "openva-observation-feed" in feed_text
    assert "site/feed-artifact/feed/observations.json" in feed_text
