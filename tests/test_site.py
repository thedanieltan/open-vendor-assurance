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


def read_source_text() -> str:
    paths = [
        SITE / "src" / "index.html",
        SITE / "src" / "app.js",
        SITE / "src" / "styles.css",
        SITE / "build.py",
        SITE / "README.md",
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def workflow_triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow.get(True) or {}


def test_site_static_build_passes_and_generates_public_data(tmp_path):
    out = build_site(tmp_path)

    assert (out / "index.html").is_file()
    assert (out / "styles.css").is_file()
    assert (out / "app.js").is_file()
    assert (out / "data" / "catalog-data.json").is_file()
    assert (out / "data" / "observation-feed.json").is_file()
    assert (out / ".nojekyll").is_file()

    catalog = json.loads((out / "data" / "catalog-data.json").read_text(encoding="utf-8"))
    assert catalog["meta"]["profileId"] == "openva.public-metadata.v1"
    assert catalog["meta"]["schemaVersion"] == "openva-export-pack.v1"
    assert catalog["meta"]["packId"] == "open-vendor-assurance"
    assert catalog["meta"]["commit_sha"]
    assert catalog["meta"]["catalog_snapshot_identity"]
    assert catalog["vendors"]
    assert catalog["sources"]
    assert catalog["sources"][0]["record_class"] == "canonical"
    assert catalog["sources"][0]["catalog_tier"] == "human_reviewed"
    assert catalog["sources"][0]["review_state"] == "human_reviewed"
    assert catalog["sources"][0]["advisory_boundary"] == "non_advisory"


def test_site_pages_include_boundary_snapshot_and_navigation_text():
    text = read_source_text()

    for phrase in [
        "OpenVA Catalog Viewer is a read-only view of public OpenVA metadata.",
        "Reviewed catalog snapshot",
        "This catalog is a read-only view of an OpenVA public metadata snapshot, not a live monitoring feed.",
        "GitHub Releases",
        "Reviewed Catalog",
        "Live Observation Feed",
        "Need to match your private vendor inventory?",
        "optional self-hosted match service",
    ]:
        assert phrase in text


def test_reviewed_catalog_ui_renders_public_metadata_and_filters_without_uploads():
    text = read_source_text()
    lower_text = text.lower()

    for phrase in [
        "search-input",
        "source-type-filter",
        "country-filter",
        "category-filter",
        "coverage-filter",
        "vendor-list",
        "renderVendorDetail",
        "data/catalog-data.json",
        "data/observation-feed.json",
    ]:
        assert phrase in text
    for phrase in [
        "canonical source records",
        "candidate source records",
        "unavailable source notes",
    ]:
        assert phrase in lower_text
    assert 'type="file"' not in text
    assert "upload vendor inventory" not in text.lower()
    assert "paste private vendor list" not in text.lower()


def test_selection_is_memory_only_and_exports_reviewed_public_metadata():
    app = (SITE / "src" / "app.js").read_text(encoding="utf-8")
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [SITE / "src" / "index.html", SITE / "src" / "app.js", SITE / "build.py"]
    )

    assert "const selectedVendors = new Set();" in app
    assert "const selectedSources = new Set();" in app
    assert "localStorage" not in source_text
    assert "sessionStorage" not in source_text
    assert "openva-selected-vendors.csv" in app
    assert "openva-selected-sources.csv" in app
    assert "openva-selected-records.json" in app
    assert "export_scope" in app
    assert "reviewed_catalog" in app
    for field in ["profileId", "schemaVersion", "packId", "schema_version", "release_tag", "commit_sha"]:
        assert field in app


def test_live_feed_shell_has_empty_state_and_noncanonical_contract(tmp_path):
    out = build_site(tmp_path)
    feed = json.loads((out / "data" / "observation-feed.json").read_text(encoding="utf-8"))
    text = read_source_text()

    assert feed["events"] == []
    assert "No live observation events are available yet." in text
    assert "observation ledger workflow" in text
    assert feed["contract"]["canonical"] is False
    assert feed["contract"]["catalog_tier"] == "observation"
    assert "auto_observed" in feed["contract"]["review_state"]
    assert "human_review_required" in feed["contract"]["review_state"]
    assert feed["contract"]["advisory_boundary"] == "non_advisory"
    assert "materiality determinations" in text
    assert "Content hash changed. Human review may be required." in text


def test_live_feed_fixture_events_are_labelled_noncanonical():
    fixture = json.loads((SITE / "fixtures" / "sample-observation-feed.json").read_text(encoding="utf-8"))
    event = fixture["events"][0]

    assert event["canonical"] is False
    assert event["catalog_tier"] == "observation"
    assert event["review_state"] == "auto_observed"
    assert event["advisory_boundary"] == "non_advisory"


def test_site_has_no_private_inventory_endpoint_or_forbidden_product_claims():
    text = read_source_text().lower()

    for forbidden in [
        "api/upload",
        "inventory upload",
        "server-side private inventory matching",
        "create account",
        "save workspace",
        "risk scoring",
        "vendor approval workflow",
        "procurement recommendation engine",
        "ai chat",
    ]:
        assert forbidden not in text
    for forbidden_claim in [
        "openva approves",
        "openva certifies",
        "openva scores",
        "openva recommends vendors",
        "openva provides compliance conclusions",
        "determines vendor compliance",
        "determines vendor safety",
    ]:
        assert forbidden_claim not in text


def test_generated_site_data_is_derived_from_public_pack_and_indexes_only():
    build_script = (SITE / "build.py").read_text(encoding="utf-8")

    assert "openva-pack.json" in build_script
    assert "indexes/vendor-search.json" in build_script
    assert "indexes/sources.json" in build_script
    assert "indexes/source-coverage.json" in build_script
    assert "data/vendors" not in build_script
    assert "fixtures/sample-observation-feed.json" not in build_script


def test_github_pages_workflows_use_expected_triggers_permissions_and_actions():
    reviewed = yaml.safe_load((WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8"))
    feed = yaml.safe_load((WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8"))

    required_permissions = {"contents": "read", "pages": "write", "id-token": "write"}
    assert reviewed["permissions"] == required_permissions
    assert feed["permissions"] == required_permissions
    assert workflow_triggers(reviewed)["push"] == {"tags": ["v*"]}
    assert workflow_triggers(feed)["schedule"][0]["cron"] == "0 3 * * 0"
    assert "workflow_dispatch" in workflow_triggers(feed)

    workflow_text = "\n".join(
        [
            (WORKFLOWS / "site-pages.yml").read_text(encoding="utf-8"),
            (WORKFLOWS / "site-live-feed.yml").read_text(encoding="utf-8"),
        ]
    )
    for phrase in [
        "actions/configure-pages@v5",
        "actions/upload-pages-artifact@v4",
        "actions/deploy-pages@v4",
        "path: site/dist",
        "python site/build.py --out site/dist",
        "assert data['events'] == []",
    ]:
        assert phrase in workflow_text


def test_site_docs_and_launch_checklist_cover_pages_boundaries():
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "README.md",
            ROOT / "docs" / "release-downloads.md",
            ROOT / "docs" / "public-launch-checklist.md",
            SITE / "README.md",
        ]
    )

    for phrase in [
        "Hosted catalog viewer and live observation feed",
        "The live feed UI shell currently ships with an empty state.",
        "The site is deployed to GitHub Pages from the static site build output.",
        "Hosted catalog viewer is read-only.",
        "Site is deployed to GitHub Pages from static build output.",
        "Site clearly separates reviewed catalog records from live observation events.",
        "Live feed UI shell displays an empty state until observation ledger/feed generation ships.",
        "Site does not use localStorage or sessionStorage for selections.",
        "GitHub Pages deployment workflow includes `contents: read`, `pages: write`, and `id-token: write` permissions.",
        "0 3 * * 0",
    ]:
        assert phrase in text
