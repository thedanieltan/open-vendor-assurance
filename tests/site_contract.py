import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
WORKFLOWS = ROOT / ".github" / "workflows"
SITE_BUILD_MODULE = None


def site_build_module():
    global SITE_BUILD_MODULE
    if SITE_BUILD_MODULE is None:
        spec = importlib.util.spec_from_file_location("openva_site_build", SITE / "build.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        SITE_BUILD_MODULE = module
    return SITE_BUILD_MODULE


def build_site(
    tmp_path: Path,
    source_health_snapshot: Path | None = None,
    assurance_intelligence: Path | None = None,
    catalog_completeness: Path | None = None,
    entity_review: Path | None = None,
    field_provenance: Path | None = None,
) -> Path:
    out = tmp_path / "site-dist"
    module = site_build_module()
    original_commit_sha = module.commit_sha
    original_commit_date = module.commit_date
    original_release_tag = module.release_tag
    module.commit_sha = lambda: "test-site-commit"
    module.commit_date = lambda: "2026-06-30T00:00:00+00:00"
    module.release_tag = lambda: ""
    try:
        module.build_site(
            out,
            source_health_snapshot or module.DEFAULT_SOURCE_HEALTH_SNAPSHOT,
            assurance_intelligence or module.DEFAULT_ASSURANCE_INTELLIGENCE_SNAPSHOT,
            catalog_completeness or module.DEFAULT_CATALOG_COMPLETENESS_REPORT,
            entity_review or module.DEFAULT_ENTITY_REVIEW_QUEUE,
            field_provenance or module.DEFAULT_FIELD_PROVENANCE_COVERAGE,
        )
    finally:
        module.commit_sha = original_commit_sha
        module.commit_date = original_commit_date
        module.release_tag = original_release_tag
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


def write_assurance_intelligence_snapshot(path: Path, vendor_id: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.1.0",
        "report_type": "assurance_intelligence_public_snapshot",
        "snapshot_type": "artifact_derived",
        "projection_profile": "openva.assurance-intelligence.v1",
        "publication_policy": {
            "id": "openva.assurance-intelligence-publication.default",
            "version": "0.1.0",
        },
        "summary": {"assurance_count": 1, "axis_count": 5},
        "entries": [
            {
                "assurance_id": "site-test-assurance",
                "vendor_id": vendor_id,
                "assurance_label": "Site Test Assurance",
                "assurance_class": "accredited_certification",
                "framework_id": "iso-27001",
                "framework_display_name": "ISO 27001",
                "projection_profile": "openva.assurance-intelligence.v1",
                "effective_at": "2026-06-30T00:00:00Z",
                "knowledge_cutoff": "2026-06-30T00:00:00Z",
                "next_reevaluation_at": "2026-07-30T00:00:00Z",
                "axes": {
                    "instrument_state": {"value": "effective", "reason_code": "effective_at_within_stated_interval"},
                    "supersession_state": {"value": "current", "reason_code": "no_explicit_successor_admitted"},
                    "verification_state": {"value": "confirmed", "reason_code": "decisive_observations_support"},
                    "verification_freshness": {
                        "value": "current",
                        "reason_code": "decisive_basis_within_current_threshold",
                    },
                    "evidence_set_state": {"value": "complete", "reason_code": "required_evidence_complete"},
                },
            }
        ],
        "advisory_boundary": "non_advisory",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_confidence_reports(tmp_path: Path, vendor_id: str) -> tuple[Path, Path, Path]:
    completeness = tmp_path / "catalog-completeness-report.json"
    entity = tmp_path / "entity-review-queue.json"
    provenance = tmp_path / "field-provenance-coverage.json"
    completeness.write_text(json.dumps({
        "report_type": "catalog_completeness_report",
        "vendors": [{
            "vendor_id": vendor_id,
            "completeness_bucket": "source_coverage_incomplete",
            "missing_expected_sources": ["dpa"],
            "missing_required_fields": [],
        }],
    }), encoding="utf-8")
    entity.write_text(json.dumps({
        "report_type": "entity_review_queue",
        "items": [{
            "vendor_id": vendor_id,
            "issue_type": "missing_legal_entity",
        }],
    }), encoding="utf-8")
    provenance.write_text(json.dumps({
        "report_type": "field_provenance_coverage",
        "vendors": [{
            "vendor_id": vendor_id,
            "coverage_bucket": "mixed",
            "covered_fields": ["legal_entity_name"],
            "missing_fields": ["dpa_url"],
        }],
    }), encoding="utf-8")
    return completeness, entity, provenance


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
    assert (out / "data" / "assurance-intelligence.json").is_file()
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
    assurance = json.loads((out / "data" / "assurance-intelligence.json").read_text(encoding="utf-8"))
    assert assurance["report_type"] == "assurance_intelligence_public_snapshot"
    assert assurance["snapshot_type"] == "empty"


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
            # A canonical source is human_reviewed, or quarantined: quarantine is a reversible,
            # status-only transition (tools/openva/source_quarantine.py) that flips only
            # review_state for a persistently not-found/gone source, leaving it canonical and
            # human_reviewed-tier. Both are valid review states for a canonical source.
            assert source["review_state"] in ("human_reviewed", "quarantined")
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
    assert row["source_health"]["label"] == "Reachable at last check"
    assert row["source_health"]["status"] == "redirected"
    assert row["source_health"]["verified_at"] == "2026-05-24T12:00:00Z"
    assert row["source_health"]["final_url"] == final_url


def test_source_with_no_health_row_shows_no_source_health_observation(tmp_path):
    matched, missing = source_rows(2)
    snapshot = write_source_health_snapshot(
        tmp_path / "source-health-snapshot.json",
        [health_row(matched, "ok", "healthy")],
    )

    out = build_site(tmp_path, snapshot)
    row = shard_source(vendor_shard(out, missing["vendor_id"]), missing["source_id"], missing["source_url"])

    assert row["source_health"]["status_bucket"] == "missing"
    assert row["source_health"]["label"] == "No source-health observation"
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
    assert row["source_health"]["label"] == "Unavailable at last check"
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

    assert warning_row["source_health"]["label"] == "Retrieval requires review"
    assert warning_row["source_health"]["description"] == "Retrieval requires review based on the latest maintenance snapshot."
    assert ambiguous_row["source_health"]["label"] == "Access result ambiguous"
    assert ambiguous_row["source_health"]["description"] == "Access result ambiguous in the latest maintenance snapshot."


def test_site_build_works_when_source_health_snapshot_is_absent(tmp_path):
    missing_snapshot = tmp_path / "missing" / "source-health-snapshot.json"
    out = build_site(tmp_path, missing_snapshot)
    source = source_rows(1)[0]
    row = shard_source(vendor_shard(out, source["vendor_id"]), source["source_id"], source["source_url"])

    assert row["source_health"]["label"] == "No source-health observation"
    fallback = json.loads((out / "data" / "source-health-snapshot.json").read_text(encoding="utf-8"))
    assert fallback["snapshot_type"] == "missing"
    assert fallback["metadata"]["missing_snapshot"] is True


def test_static_vendor_pages_use_reachability_wording_for_healthy_source_health(tmp_path):
    source = source_rows(1)[0]
    snapshot = write_source_health_snapshot(
        tmp_path / "source-health-snapshot.json",
        [health_row(source, "ok", "healthy")],
    )

    out = build_site(tmp_path, snapshot)
    page = (out / "vendors" / source["vendor_id"] / "index.html").read_text(encoding="utf-8")

    assert "Reachable at last check" in page
    assert "Not yet verified" not in page
    assert "Verified" not in page


def test_static_vendor_pages_use_neutral_wording_for_missing_source_health(tmp_path):
    source = source_rows(1)[0]
    snapshot = write_source_health_snapshot(tmp_path / "source-health-snapshot.json", [])

    out = build_site(tmp_path, snapshot)
    page = (out / "vendors" / source["vendor_id"] / "index.html").read_text(encoding="utf-8")

    assert "No source-health observation" in page
    assert "Not yet verified" not in page
    assert "Verified" not in page


def test_frontend_uses_compiled_outputs_and_on_demand_vendor_shards():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        'fetch("data/meta.json")',
        'fetch("data/vendor-search.min.json")',
        'fetch("data/source-types.json")',
        'fetch("data/source-health-snapshot.json")',
        'fetch("data/assurance-intelligence.json")',
        "const vendorDetailsCache = new Map();",
        "const sourceCache = new Map();",
        "async function loadVendorDetail",
        "fetch(vendor.detail_path)",
        "await loadVendorDetail",
    ]:
        assert phrase in app

    assert "data/catalog-data.json" not in app
    assert "maintenance/assurance-intelligence" not in app


def test_site_data_joins_assurance_intelligence_from_public_snapshot(tmp_path):
    source = source_rows(1)[0]
    snapshot = write_assurance_intelligence_snapshot(
        tmp_path / "assurance-intelligence.json",
        source["vendor_id"],
    )

    out = build_site(tmp_path, assurance_intelligence=snapshot)
    shard = vendor_shard(out, source["vendor_id"])
    public_snapshot = json.loads((out / "data" / "assurance-intelligence.json").read_text(encoding="utf-8"))

    assert public_snapshot["summary"]["assurance_count"] == 1
    assert shard["vendor"]["assurance_intelligence_count"] == 1
    assert shard["assurance_intelligence"][0]["assurance_id"] == "site-test-assurance"
    assert shard["assurance_intelligence"][0]["axes"]["verification_state"]["value"] == "confirmed"


def test_assurance_intelligence_ui_labels_are_public_and_non_advisory():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        "Assurance Intelligence",
        "Instrument",
        "Supersession",
        "Verification",
        "Freshness",
        "Evidence",
        "Confirmed",
        "No conclusion",
        "No freshness basis",
        "Conflicted",
        "Source reachability is separate from assurance verification.",
    ]:
        assert phrase in app

    assert "input_digest" not in app
    assert "projection_ref" not in app
    assert "assurance_observation_ids" not in app
    assert "source_observation_ids" not in app


def test_assurance_intelligence_public_output_excludes_internal_fields(tmp_path):
    source = source_rows(1)[0]
    snapshot = write_assurance_intelligence_snapshot(
        tmp_path / "assurance-intelligence.json",
        source["vendor_id"],
    )
    out = build_site(tmp_path, assurance_intelligence=snapshot)

    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            out / "data" / "assurance-intelligence.json",
            out / "data" / "vendors" / f"{source['vendor_id']}.json",
        ]
    )
    for forbidden in [
        "input_digest",
        "projection_ref",
        "maintenance/",
        "caused_by",
        "assurance_observation_ids",
        "source_observation_ids",
    ]:
        assert forbidden not in public_text


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
        "RESULT_PACK_VERSION",
        "RESULT_PACK_SOURCE_TYPES",
        "browserResultPackRow",
        "resultPackCsv",
        "parseCsv",
        "matchInventoryRow",
        "openva_identity_status",
        "`openva_${sourceType}_basis`",
    ]:
        assert phrase in app

    assert "localStorage" not in source_text
    assert "sessionStorage" not in source_text
    assert "FormData" not in source_text
    assert "XMLHttpRequest" not in source_text


def test_browser_local_result_pack_is_cached_and_never_live_found():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")
    cached_source_block = app.split("function cachedSourceResult", 1)[1].split("function cachedSourceUrlsByType", 1)[0]
    result_pack_block = app.split("function browserResultPackRow", 1)[1].split("function flattenResultPackRows", 1)[0]
    csv_block = app.split("function resultPackCsv", 1)[1].split("function detailSourceSummary", 1)[0]

    assert "result_pack_version: RESULT_PACK_VERSION" in result_pack_block
    assert 'identity_status: matched ? "match" : "no_match"' in result_pack_block
    assert 'status: "not_checked"' in cached_source_block
    assert 'basis: "cached"' in cached_source_block
    assert "checked_at: null" in cached_source_block
    assert 'basis: "live"' not in app
    assert 'status: "found"' not in cached_source_block
    assert "RESULT_PACK_FLAT_COLUMNS" in csv_block
    assert "openva_not_advice" in app


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
        "result_pack_version: 1.0.0",
    ]:
        assert phrase in text

    assert 'id="inventory-file"' in text
    assert 'type="file"' in text
    assert "method=\"post\"" not in text.lower()


def test_source_health_display_uses_non_advisory_labels_and_conditional_final_url():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        'healthy: "Reachable at last check"',
        'warning: "Retrieval requires review"',
        'unavailable: "Unavailable at last check"',
        'ambiguous: "Access result ambiguous"',
        'missing: "No source-health observation"',
        "Bucket counts: reachable at last check",
        "/ retrieval requires review",
        "/ unavailable at last check",
        "/ access result ambiguous",
        "Source health is based on the latest maintenance snapshot and may change.",
        "health.final_url && health.final_url !== source.source_url",
        "last checked",
    ]:
        assert phrase in app

    label_block = app.split("const SOURCE_HEALTH_LABELS = {", 1)[1].split("};", 1)[0].lower()
    for forbidden in ["trusted", "approved", "compliant", "safe", "canonical"]:
        assert forbidden not in label_block


def test_vendor_shards_include_separate_catalog_confidence_labels(tmp_path):
    source = source_rows(1)[0]
    completeness, entity, provenance = write_confidence_reports(tmp_path, source["vendor_id"])

    out = build_site(
        tmp_path,
        catalog_completeness=completeness,
        entity_review=entity,
        field_provenance=provenance,
    )
    shard = vendor_shard(out, source["vendor_id"])
    confidence = shard["vendor"]["catalog_confidence"]

    assert confidence["source_health_separate"] is True
    assert confidence["catalog_completeness"]["label"] == "Source coverage incomplete"
    assert confidence["entity_review"]["label"] == "Needs review"
    assert confidence["field_provenance"]["label"] == "Mixed"
    assert "not advice" in confidence["notice"]


def test_catalog_confidence_falls_back_when_reports_are_absent(tmp_path):
    out = build_site(tmp_path)
    vendor = json.loads((out / "data/vendor-search.min.json").read_text(encoding="utf-8"))["items"][0]
    confidence = vendor["catalog_confidence"]

    assert confidence["catalog_completeness"]["label"] == "Not reviewed"
    assert confidence["entity_review"]["label"] == "Not reviewed"
    assert confidence["field_provenance"]["label"] == "Missing"
    assert confidence["source_health_separate"] is True


def test_catalog_confidence_ui_labels_are_separate_and_non_advisory():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")

    for phrase in [
        "Catalog completeness",
        "Entity review",
        "Field provenance",
        "Shown per source record",
        "Catalog confidence labels are metadata about OpenVA review coverage, not advice.",
    ]:
        assert phrase in app

    confidence_block = app.split("function confidenceTemplate", 1)[1].split("function renderSnapshotDisclosures", 1)[0].lower()
    for forbidden in ["trusted", "approved", "compliant", "safe", "canonical"]:
        assert forbidden not in confidence_block


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
    assert "Download latest catalog confidence reports" in reviewed_text
    assert "--workflow coverage-audit.yml" in reviewed_text
    assert "--name openva-coverage-audit-report" in reviewed_text
    assert "catalog-completeness-report.json entity-review-queue.json field-provenance-coverage.json" in reviewed_text
    assert "coverage-audit-artifacts/reports/$report" in reviewed_text
    assert "coverage-audit-artifacts/$report" in reviewed_text
    assert "reports/$report" in reviewed_text
    assert "catalog confidence reports unavailable" in reviewed_text
    assert reviewed_text.index("Download latest source health snapshot") < reviewed_text.index("Build reviewed catalog site")
    assert reviewed_text.index("Download latest catalog confidence reports") < reviewed_text.index("Build reviewed catalog site")
    assert "Build Assurance Intelligence public snapshot" in reviewed_text
    assert "python -m tools.openva.assurance_intelligence_publication build --output public/assurance-intelligence.json" in reviewed_text
    assert reviewed_text.index("Build Assurance Intelligence public snapshot") < reviewed_text.index("Build reviewed catalog site")
    assert "actions/deploy-pages@v4" in reviewed_text
    assert "actions/deploy-pages" not in feed_text
    assert "actions/upload-artifact@v6" in feed_text
    assert "openva-observation-feed" in feed_text


def test_site_docs_cover_compiled_distribution_and_public_boundaries():
    readme_text = (SITE / "README.md").read_text(encoding="utf-8")
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            SITE / "README.md",
            ROOT / "docs" / "public-launch-checklist.md",
            ROOT / "docs" / "release-downloads.md",
        ]
    )

    for phrase in [
        "static OpenVA contract and community-index browser",
        "Static site",
        "Resolver contract documentation",
        "Community index browser",
        "Local resolver / CLI / MCP entry point",
        "Result-pack preview",
        "Configurable source-pack builder",
        "Browser-local resolver",
        "Source pack preview",
        "Export Source Pack",
        "compiled static distribution",
        "vendor-search.min.json",
        "data/vendors/{vendor_id}.json",
        "browser memory only",
        "not written to `localStorage`, `sessionStorage`, a server, or a database",
        "no backend, database, account system, upload endpoint",
        "no live verification job",
        "no live discovery job",
        "no hosted resolver worker",
        "community index is hint-only",
        "consumer-side live verification",
        "openva_{source_type}_candidate_basis",
        "openva_{source_type}_verification_basis",
        "no server-side workspace persistence",
        "public metadata",
    ]:
        assert phrase in text

    for phrase in [
        "Hosted site uses compiled/sharded catalog outputs",
        "Vendor detail records are generated",
        "Browser-local matcher still processes private inventories in memory only",
        "compiled catalog distribution",
    ]:
        assert phrase not in readme_text
