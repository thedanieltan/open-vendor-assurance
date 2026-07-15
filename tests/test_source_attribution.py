
import json
import runpy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from tools.openva.catalog_guard import validate_changed_source_attribution
from tools.openva.source_attribution import (
    build_source_attribution_report,
    classify_source,
    source_requires_attribution,
    validate_source_attribution,
)

ROOT = Path(__file__).resolve().parents[1]
ACUITY_SOURCE_DIR = ROOT / "data/vendors/acuity-scheduling/sources"


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_acuity_cross_domain_sources_have_explainable_parent_attribution():
    vendor = load_yaml(ROOT / "data/vendors/acuity-scheduling/vendor.yaml")
    for path in sorted(ACUITY_SOURCE_DIR.glob("*.yaml")):
        source = load_yaml(path)
        assert source_requires_attribution(source, vendor)
        assert validate_source_attribution(source, vendor) == []
        classification, issues = classify_source(source, vendor)
        assert classification == "attributed_parent"
        assert issues == []
        assert source["publisher_attribution"]["publisher_name"] == "Squarespace"
        assert source["applicability"]["covered_products"] == ["Acuity Scheduling"]


def test_cross_domain_source_without_applicability_fails_closed():
    vendor = {"official_domains": ["product.example"]}
    source = {
        "source_url": "https://parent.example/privacy",
        "source_id": "product-privacy",
        "vendor_id": "product",
    }
    failures = validate_source_attribution(source, vendor)
    assert "cross-domain source is missing publisher_attribution" in failures
    assert "cross-domain source is missing applicability" in failures
    assert classify_source(source, vendor)[0] == "unproven_cross_domain"


def test_same_product_domain_remains_backward_compatible():
    vendor = {"official_domains": ["product.example"]}
    source = {"source_url": "https://www.product.example/privacy"}
    assert not source_requires_attribution(source, vendor)
    assert validate_source_attribution(source, vendor) == []
    assert classify_source(source, vendor) == ("same_product_domain", [])


def test_source_schema_accepts_attribution_and_applicability():
    schema = json.loads((ROOT / "schemas/openva/source-reference.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for path in sorted(ACUITY_SOURCE_DIR.glob("*.yaml")):
        errors = sorted(validator.iter_errors(load_yaml(path)), key=lambda error: list(error.path))
        assert errors == []


def test_changed_record_gate_accepts_attributed_acuity_sources():
    paths = [path.relative_to(ROOT).as_posix() for path in sorted(ACUITY_SOURCE_DIR.glob("*.yaml"))]
    assert validate_changed_source_attribution(paths, root=ROOT) == []


def test_audit_is_report_only_and_surfaces_cross_domain_inventory():
    report = build_source_attribution_report(ROOT)
    assert report["report_type"] == "source_publisher_attribution_audit"
    assert report["posture"] == {
        "network_fetch_performed": False,
        "writes_repository_state": False,
        "mutates_catalog": False,
        "non_advisory": True,
    }
    acuity = [row for row in report["sources"] if row["vendor_id"] == "acuity-scheduling"]
    assert len(acuity) == 5
    assert {row["classification"] for row in acuity} == {"attributed_parent"}


def test_site_projection_and_export_contract_preserve_attribution():
    source = load_yaml(ACUITY_SOURCE_DIR / "acuity-scheduling-privacy.yaml")
    build_core = runpy.run_path(str(ROOT / "site/build_core.py"))
    compact = build_core["compact_source"](source)
    assert compact["publisher_attribution"]["relationship"] == "parent"
    assert compact["applicability"]["status"] == "verified"

    app = (ROOT / "site/src/app.js").read_text(encoding="utf-8")
    assert "Why this source applies" in app
    assert "Parent-company source" in app
    assert "publisher_attribution" in app
    assert "applicability" in app

    csv_exporter = (
        ROOT / "adapters/python/openva_csv_export/openva_csv_export/exporter.py"
    ).read_text(encoding="utf-8")
    sqlite_exporter = (
        ROOT / "adapters/python/openva_sqlite_export/openva_sqlite_export/exporter.py"
    ).read_text(encoding="utf-8")
    for field in ("publisher_attribution", "applicability"):
        assert f'"{field}"' in csv_exporter
        assert f'"{field}": "TEXT"' in sqlite_exporter


def test_source_maintenance_workflow_publishes_attribution_audit():
    workflow = (ROOT / ".github/workflows/source-maintenance-report.yml").read_text(encoding="utf-8")
    assert "python -m tools.openva.source_attribution audit" in workflow
    assert "source-attribution-audit.json" in workflow
