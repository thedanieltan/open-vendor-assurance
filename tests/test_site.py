import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
WORKFLOWS = ROOT / ".github" / "workflows"


def build_site(tmp_path: Path, source_health_snapshot: Path | None = None) -> Path:
    out = tmp_path / "site-dist"
    args = [sys.executable, "site/build.py", "--out", str(out)]
    if source_health_snapshot:
        args.extend(["--source-health-snapshot", str(source_health_snapshot)])
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return out


def source_rows(limit: int = 4) -> list[dict]:
    sources = json.loads((ROOT / "indexes" / "sources.json").read_text(encoding="utf-8"))["items"]
    rows = [
        row
        for row in sources
        if row.get("vendor_id") and row.get("source_id") and row.get("source_url")
    ]
    assert len(rows) >= limit
    return rows[:limit]


def write_source_health_snapshot(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"healthy": 0, "warning": 0, "unavailable": 0, "ambiguous": 0}
    for row in rows:
        counts[row["status_bucket"]] += 1
    payload = {
        "schema_version": "0.1.0",
        "generated_at": "2026-05-24T12:30:00Z",
        "report_type": "source_health_public_snapshot",
        "source": "latest-source-health",
        "snapshot_type": "artifact_derived",
        "metadata": {
            "snapshot_notice": "Source health is based on the latest maintenance snapshot and may change.",
            "non_advisory": True,
        },
        "summary": {"source_count": len(rows), "status_bucket_counts": counts},
        "health": rows,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def health_row(source: dict, status: str, bucket: str, *, final_url: str | None = None) -> dict:
    return {
        "vendor_id": source["vendor_id"],
        "source_id": source["source_id"],
        "source_url": source["source_url"],
        "status": status,
        "status_bucket": bucket,
        "http_status": 200 if bucket != "unavailable" else 410,
        "final_url": final_url or source["source_url"],
        "verified_at": "2026-05-24T12:00:00Z",
        "run_id": "26360606605",
        "observer": "source-verification-report",
    }


def vendor_shard(out: Path, vendor_id: str) -> dict:
    return json.loads((out / "data" / "vendors" / f"{vendor_id}.json").read_text(encoding="utf-8"))


def shard_source(shard: dict, source_id: str, source_url: str) -> dict:
    for source in shard["canonical_sources"]:
        if source["source_id"] == source_id and source["source_url"] == source_url:
            return source
    raise AssertionError(f"source not found: {source_id} {source_url}")


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_site_static_build_passes_and_generates_compiled_distribution(tmp_path):
    out = build_site(tmp_path)

    assert (out / "index.html").is_file()
    assert (out / "data" / "meta.json").is_file()
    assert (out / "data" / "vendor-search.min.json").is_file()
    assert (out / "data" / "source-types.json").is_file()
    assert (out / "data" / "coverage-summary.json").is_file()
    assert (out / "data" / "source-health-snapshot.json").is_file()
    assert (out / "data" / "observation-feed.json").is_file()
    assert not (out / "data" / "catalog-data.json").exists()

    meta = json.loads((out / "data" / "meta.json").read_text(encoding="utf-8"))
    assert meta["profileId"] == "openva.public-metadata.v1"
    assert meta["schemaVersion"] == "openva-export-pack.v1"
    assert meta["packId"] == "open-vendor-assurance"
    assert meta["compiled_distribution"] is True
    assert meta["site_data_contract"] == "openva-site-compiled-catalog.v1"

    health = json.loads((out / "data" / "source-health-snapshot.json").read_text(encoding="utf-8"))
    assert health["snapshot_type"] == "missing"
    assert health["summary"]["status_bucket_counts"] == {
        "healthy": 0,
        "warning": 0,
        "unavailable": 0,
        "ambiguous": 0,
    }


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


def test_source_health_snapshot_joins_to_source_rows_by_identity(tmp_path):
    source = source_rows(1)[0]
    final_url = source["source_url"].rstrip("/") + "/current"
    snapshot = write_source_health_snapshot(
        tmp_path / "source-health-snapshot.json",
        [health_row(source, "redirected", "healthy", final_url=final_url)],
    )

    out = build_site(tmp_path, snapshot)
    shard = vendor_shard(out, source["vendor_id"])
    row = shard_source(shard, source["source_id"], source["source_url"])

    assert row["source_health"]["status_bucket"] == "healthy"
    assert row["source_health"]["label"] == "Verified"
    assert row["source_health"]["status"] == "redirected"
    assert row["source_health"]["verified_at"] == "2026-05-24T12:00:00Z"
    assert row["source_health"]["final_url"] == final_url


def test_source_with_no_health_row_shows_not_yet_verified(tmp_path):
    matched, missing = source_rows(2)
    snapshot = write_source_health_snapshot(
        tmp_path / "source-health-snapshot.json",
        [health_row(matched, "ok", "healthy")],
    )

    out = build_site(tmp_path, snapshot)
    row = shard_source(vendor_shard(out, missing["vendor_id"]), missing["source_id"], missing["source_url"])

    assert row["source_health"]["status_bucket"] == "missing"
    assert row["source_health"]["label"] == "Not yet verified"
    assert row["source_health"]["status"] is None
    assert row["source_health"]["verified_at"] is None


def test_unavailable_source_remains_visible_and_labelled_unavailable(tmp_path):
    source = source_rows(1)[0]
    snapshot = write_source_health_snapshot(
        tmp_path / "source-health-snapshot.json",
        [health_row(source, "gone", "unavailable")],
    )

    out = build_site(tmp_path, snapshot)
    row = shard_source(vendor_shard(out, source["vendor_id"]), source["source_id"], source["source_url"])

    assert row["source_url"] == source["source_url"]
    assert row["source_health"]["status_bucket"] == "unavailable"
    assert row["source_health"]["label"] == "Unavailable"
    assert row["source_health"]["status"] == "gone"


def test_warning_and_ambiguous_source_health_labels_are_factual(tmp_path):
    warning, ambiguous = source_rows(2)
    snapshot = write_source_health_snapshot(
        tmp_path / "source-health-snapshot.json",
        [
            health_row(warning, "possible_mismatch", "warning"),
            health_row(ambiguous, "bot_protected", "ambiguous"),
        ],
    )

    out = build_site(tmp_path, snapshot)
    warning_row = shard_source(vendor_shard(out, warning["vendor_id"]), warning["source_id"], warning["source_url"])
    ambiguous_row = shard_source(vendor_shard(out, ambiguous["vendor_id"]), ambiguous["source_id"], ambiguous["source_url"])

    assert warning_row["source_health"]["label"] == "Needs review"
    assert warning_row["source_health"]["description"] == "Needs review based on the latest maintenance snapshot."
    assert ambiguous_row["source_health"]["label"] == "Access ambiguous"
    assert ambiguous_row["source_health"]["description"] == "Access ambiguous in the latest maintenance snapshot."


def test_site_build_works_when_source_health_snapshot_is_absent(tmp_path):
    missing_snapshot = tmp_path / "missing" / "source-health-snapshot.json"
    out = build_site(tmp_path, missing_snapshot)
    source = source_rows(1)[0]
    row = shard_source(vendor_shard(out, source["vendor_id"]), source["source_id"], source["source_url"])

    assert row["source_health"]["label"] == "Not yet verified"
    fallback = json.loads((out / "data" / "source-health-snapshot.json").read_text(encoding="utf-8"))
    assert fallback["snapshot_type"] == "missing"
    assert fallback["metadata"]["missing_snapshot"] is True


def test_frontend_uses_compiled_outputs_and_on_demand_vendor_shards():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        'fetch("data/meta.json")',
        'fetch("data/vendor-search.min.json")',
        'fetch("data/source-types.json")',
        'fetch("data/source-health-snapshot.json")',
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


def test_source_health_display_uses_non_advisory_labels_and_conditional_final_url():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        'healthy: "Verified"',
        'warning: "Needs review"',
        'unavailable: "Unavailable"',
        'ambiguous: "Access ambiguous"',
        'missing: "Not yet verified"',
        "Source health is based on the latest maintenance snapshot and may change.",
        "health.final_url && health.final_url !== source.source_url",
        "last checked",
    ]:
        assert phrase in app

    label_block = app.split("const SOURCE_HEALTH_LABELS = {", 1)[1].split("};", 1)[0].lower()
    for forbidden in ["trusted", "approved", "compliant", "safe"]:
        assert forbidden not in label_block


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

    assert reviewed["permissions"] == {"contents": "read", "actions": "read", "pages": "write", "id-token": "write"}
    assert feed["permissions"] == {"contents": "read"}
    assert workflow_triggers(reviewed)["push"] == {"branches": ["main"]}
    assert "workflow_dispatch" in workflow_triggers(reviewed)
    assert workflow_triggers(feed)["schedule"][0]["cron"] == "0 3 * * 0"
    assert "workflow_dispatch" in workflow_triggers(feed)

    reviewed_text = (WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8")
    feed_text = (WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8")
    assert "Download latest source health snapshot" in reviewed_text
    assert "--workflow source-maintenance-report.yml" in reviewed_text
    assert "--name openva-source-maintenance-report" in reviewed_text
    assert "public/source-health-snapshot.json" in reviewed_text
    assert "source health snapshot unavailable" in reviewed_text
    assert reviewed_text.index("Download latest source health snapshot") < reviewed_text.index("Build reviewed catalog site")
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
