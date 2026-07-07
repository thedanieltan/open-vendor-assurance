import csv
import json
from io import StringIO
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.openva import resolver_result_pack as pack
from tools.openva import vendor_resolution

ROOT = Path(__file__).resolve().parents[1]


def resolved_source(source_type: str, status: str, *, live_checked: bool, url: str | None = None, reasons=None):
    return vendor_resolution.ResolvedSource(
        source_type=source_type,
        status=status,
        source_url=url,
        origin="catalog" if url else None,
        catalog_membership="canonical" if url else "none",
        live_checked=live_checked,
        checked_at="2026-07-06T00:00:00Z" if live_checked else "2026-01-01T00:00:00Z",
        catalog_status=vendor_resolution.LIFECYCLE_CATALOGUED if url else None,
        reasons=list(reasons or []),
    )


def resolution(vendor_id="example", status=vendor_resolution.RESULT_CATALOG_CURRENT, sources=None):
    return vendor_resolution.VendorResolution(
        vendor={
            "vendor_id": vendor_id,
            "display_name": "Example",
            "official_domain": "example.com",
        },
        resolution_status=status,
        freshness_mode=vendor_resolution.FRESHNESS_VERIFY,
        sources=list(sources or []),
        snapshot={
            "catalog_commit_sha": "test",
            "catalog_generated_at": "2026-07-06T00:00:00Z",
        },
    )


def validate_rows(rows):
    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(rows), key=lambda error: list(error.path))
    assert errors == []


def validation_errors(rows):
    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    return sorted(Draft202012Validator(schema).iter_errors(rows), key=lambda error: list(error.path))


def test_projected_json_is_simple_compiled_vendor_shape_and_schema_valid():
    row = {"vendor_name": "Example", "domain": "example.com"}
    result = resolution(
        sources=[
            resolved_source("trust_center", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=False, url="https://example.com/trust"),
            resolved_source("dpa", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=False, url="https://example.com/dpa"),
            resolved_source("subprocessors_list", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=False, url="https://example.com/subprocessors"),
        ]
    )

    projected = pack.project_resolution(row, 0, result)

    assert projected == {
        "result_pack_version": "2.0.0",
        "input_index": 0,
        "input_vendor_name": "Example",
        "input_domain": "example.com",
        "match_status": "matched",
        "match_reason": "domain match",
        "compiled_vendor_name": "Example",
        "compiled_domain": "example.com",
        "dpa_url": "https://example.com/dpa",
        "subprocessors_url": "https://example.com/subprocessors",
        "privacy_notice_url": None,
        "security_or_trust_url": "https://example.com/trust",
        "status_page_url": None,
        "source_status": "compiled_from_reference",
        "review_note": "Review compiled links before relying on them",
    }
    validate_rows([projected])


def test_flat_csv_preserves_input_order_and_uses_human_download_columns():
    inputs = [
        {"vendor_name": "First", "business_entity_name": "", "domain": "first.example"},
        {"vendor_name": "Second", "business_entity_name": "", "domain": "second.example"},
    ]
    rows = [
        pack.project_resolution(inputs[0], 0, resolution(vendor_id=None, status=vendor_resolution.RESULT_NOT_FOUND)),
        pack.project_resolution(
            inputs[1],
            1,
            resolution(
                sources=[
                    resolved_source(
                        "trust_center",
                        vendor_resolution.RESULT_CATALOG_REFRESHED,
                        live_checked=True,
                        url="https://second.example/trust",
                    )
                ]
            ),
        ),
    ]

    csv_text = pack.result_pack_csv(inputs, rows)
    reader = csv.DictReader(StringIO(csv_text))
    parsed = list(reader)

    assert reader.fieldnames == [
        "vendor_name",
        "business_entity_name",
        "domain",
        *pack.FLAT_RESULT_COLUMNS,
    ]
    assert [row["vendor_name"] for row in parsed] == ["First", "Second"]
    assert parsed[0]["business_entity_name"] == ""
    assert parsed[0]["match_status"] == "not_matched"
    assert parsed[0]["match_reason"] == "not in reference"
    assert parsed[0]["compiled_vendor_name"] == ""
    assert parsed[0]["source_status"] == "not_available"
    assert parsed[1]["match_status"] == "matched"
    assert parsed[1]["security_or_trust_url"] == "https://second.example/trust"
    assert "openva_not_advice" not in reader.fieldnames
    assert not any(column.startswith("openva_") for column in reader.fieldnames)


def test_schema_enum_coverage_matches_projection_constants():
    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    result_schema = schema["$defs"]["resultRow"]["properties"]

    assert tuple(result_schema["match_status"]["enum"]) == pack.MATCH_STATUSES
    assert tuple(result_schema["source_status"]["enum"]) == pack.SOURCE_STATUSES
    assert tuple(result_schema["match_reason"]["enum"][-4:]) == pack.NO_MATCH_REASONS


def test_no_match_reason_mapping_and_identity_ambiguous_collapse():
    base = {"vendor_name": "Example", "domain": "example.com"}

    ambiguous = pack.project_resolution(
        base,
        0,
        resolution(vendor_id=None, status=vendor_resolution.RESULT_IDENTITY_AMBIGUOUS),
    )
    absent = pack.project_resolution(base, 1, resolution(vendor_id=None, status=vendor_resolution.RESULT_NOT_FOUND))
    no_identity = pack.project_resolution({}, 2, resolution(vendor_id=None, status=vendor_resolution.RESULT_NOT_FOUND))
    inconclusive = pack.project_resolution(
        base,
        3,
        resolution(vendor_id=None, status=vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE),
    )

    assert ambiguous["match_status"] == "not_matched"
    assert ambiguous["match_reason"] == "multiple plausible entities"
    assert absent["match_reason"] == "not in reference"
    assert no_identity["match_reason"] == "missing vendor identity"
    assert inconclusive["match_reason"] == "inconclusive"


def test_source_type_aliases_collapse_to_human_template_columns():
    assert pack.normalize_source_types(["trust_center", "security_page", "subprocessors_list"]) == [
        "subprocessors",
        "security_or_trust",
    ]
    assert pack.resolver_source_types(["security_or_trust"]) == ["trust_center", "security_page"]

    trust = pack.project_source({"source_type": "trust_center", "source_url": "https://example.com/trust"}, "", "trust_center")
    security = pack.project_source({"source_type": "security_page", "source_url": "https://example.com/security"}, "", "security_page")

    assert trust == {"source_type": "security_or_trust", "url": "https://example.com/trust"}
    assert security == {"source_type": "security_or_trust", "url": "https://example.com/security"}


def test_result_pack_schema_rejects_retired_advice_and_branded_columns():
    row = pack.project_resolution(
        {"vendor_name": "Example", "domain": "example.com"},
        0,
        resolution(sources=[resolved_source("dpa", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=False, url="https://example.com/dpa")]),
    )
    polluted = json.loads(json.dumps(row))
    polluted["openva_not_advice"] = True

    assert validation_errors([row]) == []
    assert validation_errors([polluted])


def test_projection_uses_existing_resolver_authority_for_python_resolution():
    source = (ROOT / "tools/openva/resolver_result_pack.py").read_text(encoding="utf-8")

    assert "vendor_resolution.resolve_vendor_sources" in source
    assert "matcher." not in source


def test_agent_export_schema_version_remains_pinned():
    schema = json.loads((ROOT / "schemas/openva/agent-export.schema.json").read_text(encoding="utf-8"))
    text = (ROOT / "docs/agent-export-contract.md").read_text(encoding="utf-8")

    vendor_schema = schema["$defs"]["vendor_export"]["properties"]["schema_version"]
    assert vendor_schema == {"const": "0.1.0"}
    assert "`0.1.0`" in text


def test_local_first_doctrine_declares_runtime_boundary():
    text = (ROOT / "docs/local-first-resolution-doctrine.md").read_text(encoding="utf-8")

    assert "OpenVA does not process user vendor inventories." in text
    assert "Live resolution executes on the consumer side" in text
    assert "community index of candidate hints, never an oracle" in text
    assert "result pack is the product boundary" in text
    assert "hosted OpenVA resolver or hosted OpenVA API is explicitly out of scope" in text
