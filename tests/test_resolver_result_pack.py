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


def test_nested_json_order_is_deterministic_and_schema_valid():
    row = {"vendor_name": "Example", "domain": "example.com"}
    result = resolution(
        sources=[
            resolved_source("security_page", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=True, url="https://example.com/security"),
            resolved_source("dpa", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=False, url="https://example.com/dpa"),
        ]
    )

    projected = pack.project_resolution(row, 0, result)

    assert [source["source_type"] for source in projected["sources"]] == list(pack.SOURCE_TYPES)
    assert projected["sources"][0]["source_type"] == "trust_center"
    assert projected["sources"][1] == {
        "source_type": "dpa",
        "status": "not_checked",
        "url": "https://example.com/dpa",
        "candidate_basis": "cached_locator",
        "verification_basis": "not_checked",
        "checked_at": None,
    }
    assert projected["sources"][4]["status"] == "found"
    assert projected["sources"][4]["candidate_basis"] == "cached_locator"
    assert projected["sources"][4]["verification_basis"] == "verified_live"
    validate_rows([projected])


def test_flat_csv_preserves_input_order_and_deterministic_columns():
    inputs = [
        {"vendor_name": "First", "domain": "first.example"},
        {"vendor_name": "Second", "domain": "second.example"},
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
        "domain",
        *pack.FLAT_RESULT_COLUMNS,
    ]
    assert [row["vendor_name"] for row in parsed] == ["First", "Second"]
    assert parsed[0]["openva_identity_status"] == "no_match"
    assert parsed[1]["openva_trust_center_status"] == "found"
    assert parsed[1]["openva_trust_center_candidate_basis"] == "cached_locator"
    assert parsed[1]["openva_trust_center_verification_basis"] == "verified_live"


def test_schema_enum_coverage_matches_projection_constants():
    schema = json.loads((ROOT / "schemas/openva/resolver-result-pack.schema.json").read_text(encoding="utf-8"))
    source_schema = schema["$defs"]["sourceResult"]["properties"]
    no_match_schema = schema["$defs"]["resultRow"]["properties"]["no_match_reason"]["oneOf"][1]

    assert tuple(source_schema["source_type"]["enum"]) == pack.SOURCE_TYPES
    assert tuple(source_schema["status"]["enum"]) == pack.SOURCE_STATUSES
    assert tuple(source_schema["candidate_basis"]["enum"]) == pack.CANDIDATE_BASES
    assert tuple(source_schema["verification_basis"]["enum"]) == pack.VERIFICATION_BASES
    assert tuple(no_match_schema["enum"]) == pack.NO_MATCH_REASONS


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

    assert ambiguous["identity_status"] == "no_match"
    assert ambiguous["no_match_reason"] == "multiple_plausible_entities"
    assert absent["no_match_reason"] == "not_in_reference"
    assert no_identity["no_match_reason"] == "no_public_identity"
    assert inconclusive["no_match_reason"] == "inconclusive"


def test_source_state_mapping_does_not_overclaim_cached_or_inconclusive_results():
    cached_current = pack.project_source(
        {
            "source_type": "dpa",
            "status": vendor_resolution.RESULT_CATALOG_CURRENT,
            "source_url": "https://example.com/dpa",
            "live_checked": False,
            "checked_at": "2026-01-01T00:00:00Z",
        },
        vendor_resolution.RESULT_CATALOG_CURRENT,
        "dpa",
    )
    gated = pack.project_source(
        {
            "source_type": "privacy_notice",
            "status": vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE,
            "source_url": "https://example.com/privacy",
            "live_checked": True,
            "checked_at": "2026-07-06T00:00:00Z",
            "reasons": ["inconclusive:gated"],
        },
        vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE,
        "privacy_notice",
    )
    unavailable = pack.project_source(
        {
            "source_type": "security_page",
            "status": vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE,
            "source_url": "https://example.com/security",
            "live_checked": True,
            "checked_at": "2026-07-06T00:00:00Z",
        },
        vendor_resolution.RESULT_VERIFICATION_INCONCLUSIVE,
        "security_page",
    )

    assert cached_current == {
        "source_type": "dpa",
        "status": "not_checked",
        "url": "https://example.com/dpa",
        "candidate_basis": "cached_locator",
        "verification_basis": "not_checked",
        "checked_at": None,
    }
    assert gated["status"] == "gated"
    assert gated["verification_basis"] == "live_gated"
    assert unavailable["status"] == "unavailable"
    assert unavailable["verification_basis"] == "live_unavailable"


def test_candidate_inputs_cannot_become_verified_live_without_live_check():
    for candidate_basis in ("community_hint", "vendor_asserted", "cached_locator"):
        projected = pack.project_source(
            {
                "source_type": "dpa",
                "status": vendor_resolution.RESULT_CATALOG_CURRENT,
                "source_url": "https://example.com/dpa",
                "candidate_basis": candidate_basis,
                "live_checked": False,
                "checked_at": "2026-01-01T00:00:00Z",
            },
            vendor_resolution.RESULT_CATALOG_CURRENT,
            "dpa",
        )

        assert projected["candidate_basis"] == candidate_basis
        assert projected["status"] == "not_checked"
        assert projected["verification_basis"] == "not_checked"
        assert projected["checked_at"] is None


def test_result_pack_schema_requires_provenance_distinction():
    row = pack.project_resolution(
        {"vendor_name": "Example", "domain": "example.com"},
        0,
        resolution(sources=[resolved_source("dpa", vendor_resolution.RESULT_CATALOG_CURRENT, live_checked=False, url="https://example.com/dpa")]),
    )
    missing_candidate = json.loads(json.dumps(row))
    missing_verification = json.loads(json.dumps(row))
    del missing_candidate["sources"][1]["candidate_basis"]
    del missing_verification["sources"][1]["verification_basis"]

    assert validation_errors([row]) == []
    assert validation_errors([missing_candidate])
    assert validation_errors([missing_verification])


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


def test_contract_doc_contains_mapping_table_and_static_honesty_rule():
    text = (ROOT / "docs/resolver-result-pack-contract.md").read_text(encoding="utf-8")

    assert "| `identity_ambiguous` | `identity_status=no_match`, `no_match_reason=multiple_plausible_entities` |" in text
    assert "community index is hint-only" in text
    assert "consumer-side live verification" in text
    assert "| `catalog_current` | `status=found` only when `verification_basis=verified_live`;" in text
    assert "## Static Honesty Rule" in text
    assert "never emit `verification_basis=verified_live`" in text
    assert "never emit live `found` semantics" in text


def test_local_first_doctrine_declares_runtime_boundary():
    text = (ROOT / "docs/local-first-resolution-doctrine.md").read_text(encoding="utf-8")

    assert "OpenVA does not process user vendor inventories." in text
    assert "Live resolution executes on the consumer side" in text
    assert "community index of candidate hints, never an oracle" in text
    assert "result pack is the product boundary" in text
    assert "hosted OpenVA resolver or hosted OpenVA API is explicitly out of scope" in text
