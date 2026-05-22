import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
WORKFLOWS = ROOT / ".github" / "workflows"


def build_site(tmp_path: Path) -> Path:
    out = tmp_path / "site-dist"
    result = subprocess.run(
        [sys.executable, "site/build.py", "--out", str(out)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return out


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_site_static_build_passes_and_generates_compiled_distribution(tmp_path):
    out = build_site(tmp_path)

    assert (out / "index.html").is_file()
    assert (out / "data" / "meta.json").is_file()
    assert (out / "data" / "vendor-search.min.json").is_file()
    assert (out / "data" / "source-types.json").is_file()
    assert (out / "data" / "coverage-summary.json").is_file()
    assert (out / "data" / "observation-feed.json").is_file()
    assert not (out / "data" / "catalog-data.json").exists()

    meta = json.loads((out / "data" / "meta.json").read_text(encoding="utf-8"))
    assert meta["profileId"] == "openva.public-metadata.v1"
    assert meta["schemaVersion"] == "openva-export-pack.v1"
    assert meta["packId"] == "open-vendor-assurance"
    assert meta["compiled_distribution"] is True
    assert meta["site_data_contract"] == "openva-site-compiled-catalog.v1"


def test_vendor_search_is_lightweight_and_detail_paths_exist(tmp_path):
    out = build_site(tmp_path)
    meta = json.loads((out / "data" / "meta.json").read_text(encoding="utf-8"))
    search = json.loads((out / "data" / "vendor-search.min.json").read_text(encoding="utf-8"))

    assert search["items"]
    assert len(search["items"]) == meta["vendor_count"]

    forbidden_heavy_fields = {
        "canonical_sources",
        "candidate_sources",
        "unavailable_sources",
        "latest_observations",
    }
    for vendor in search["items"]:
        assert "detail_path" in vendor
        assert forbidden_heavy_fields.isdisjoint(vendor)
        assert (out / vendor["detail_path"]).is_file()


def test_vendor_shards_preserve_counts_and_tier_annotations(tmp_path):
    out = build_site(tmp_path)
    meta = json.loads((out / "data" / "meta.json").read_text(encoding="utf-8"))
    search = json.loads((out / "data" / "vendor-search.min.json").read_text(encoding="utf-8"))

    total_sources = 0
    shard_count = 0
    for vendor in search["items"]:
        shard = json.loads((out / vendor["detail_path"]).read_text(encoding="utf-8"))
        shard_count += 1
        assert shard["vendor"]["vendor_id"] == vendor["vendor_id"]
        for source in shard["canonical_sources"]:
            total_sources += 1
            assert source["record_class"] == "canonical"
            assert source["canonical"] is True
            assert source["catalog_tier"] == "human_reviewed"
            assert source["review_state"] == "human_reviewed"
            assert source["advisory_boundary"] == "non_advisory"
        for candidate in shard["candidate_sources"]:
            assert candidate["record_class"] == "candidate"
            assert candidate["canonical"] is False
            assert candidate["catalog_tier"] == "discovery"
            assert candidate["review_state"] == "human_review_required"
            assert candidate["advisory_boundary"] == "non_advisory"
        for observation in shard["latest_observations"]:
            assert observation["record_class"] == "observation"
            assert observation["canonical"] is False
            assert observation["catalog_tier"] == "observation"
            assert observation["advisory_boundary"] == "non_advisory"

    assert shard_count == meta["vendor_count"]
    assert total_sources == meta["source_count"]


def test_frontend_uses_compiled_outputs_and_on_demand_vendor_shards():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        'fetch("data/meta.json")',
        'fetch("data/vendor-search.min.json")',
        'fetch("data/source-types.json")',
        "const vendorDetailsCache = new Map();",
        "const sourceCache = new Map();",
        "async function loadVendorDetail",
        "fetch(vendor.detail_path)",
        "await loadVendorDetail",
    ]:
        assert phrase in app

    assert "data/catalog-data.json" not in app


def test_selection_and_browser_local_matcher_remain_memory_only():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [SITE / "src" / "index.html", SITE / "src" / "app.js", SITE / "build.py"]
    )

    for phrase in [
        "const selectedVendors = new Set();",
        "const selectedSources = new Set();",
        "localInventoryRows",
        "localMatchRows",
        "parseCsv",
        "matchInventoryRow",
        "domain_exact",
        "vendor_name_exact",
        "business_entity_name_exact",
        "browser_local_inventory_match",
    ]:
        assert phrase in app

    assert "localStorage" not in source_text
    assert "sessionStorage" not in source_text
    assert "FormData" not in source_text
    assert "XMLHttpRequest" not in source_text


def test_site_text_preserves_catalog_feed_and_matcher_boundary():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [SITE / "src" / "index.html", SITE / "src" / "app.js", SITE / "README.md"]
    )
    for phrase in [
        "Reviewed Catalog",
        "Live Observation Feed",
        "Reviewed catalog snapshot",
        "not a live monitoring feed",
        "No live observation events are available yet.",
        "observation ledger workflow",
        "Local Matcher",
        "Your CSV is processed locally in your browser. It is not uploaded to OpenVA.",
        "openva-matched-inventory.csv",
        "openva-matched-inventory.json",
    ]:
        assert phrase in text

    assert 'id="inventory-file"' in text
    assert 'type="file"' in text
    assert "method=\"post\"" not in text.lower()


def test_feed_contract_remains_empty_and_noncanonical(tmp_path):
    out = build_site(tmp_path)
    feed = json.loads((out / "data" / "observation-feed.json").read_text(encoding="utf-8"))

    assert feed["events"] == []
    assert feed["contract"]["canonical"] is False
    assert feed["contract"]["catalog_tier"] == "observation"
    assert "auto_observed" in feed["contract"]["review_state"]
    assert "human_review_required" in feed["contract"]["review_state"]
    assert feed["contract"]["advisory_boundary"] == "non_advisory"


def test_release_workflow_builds_compiled_site_distribution():
    release = (WORKFLOWS / "release-downloads.yml").read_text(encoding="utf-8")
    assert "python site/build.py --out site/dist" in release


def test_pages_workflow_deploys_site_and_feed_workflow_uploads_feed_artifact_only():
    reviewed = yaml.safe_load((WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8"))
    feed = yaml.safe_load((WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8"))

    assert reviewed["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert feed["permissions"] == {"contents": "read"}
    assert workflow_triggers(reviewed)["push"] == {"branches": ["main"]}
    assert "workflow_dispatch" in workflow_triggers(reviewed)
    assert workflow_triggers(feed)["schedule"][0]["cron"] == "0 3 * * 0"
    assert "workflow_dispatch" in workflow_triggers(feed)

    reviewed_text = (WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8")
    feed_text = (WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8")
    assert "actions/deploy-pages@v4" in reviewed_text
    assert "actions/deploy-pages" not in feed_text
    assert "actions/upload-artifact@v6" in feed_text
    assert "openva-observation-feed" in feed_text


def test_site_docs_cover_compiled_distribution_and_public_boundaries():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            SITE / "README.md",
            ROOT / "docs" / "public-launch-checklist.md",
            ROOT / "docs" / "release-downloads.md",
        ]
    )

    for phrase in [
        "compiled catalog distribution",
        "vendor-search.min.json",
        "data/vendors/{vendor_id}.json",
        "Hosted site uses compiled/sharded catalog outputs",
        "Vendor detail records are generated",
        "Browser-local matcher still processes private inventories in memory only",
    ]:
        assert phrase in text