"""Tests for the MCP composite ``enrich_inventory`` tool.

The tool is the agent-composed workspace path: an agent reads a workspace through
its own connector, then sends only bounded vendor-identity rows here. It matches with
the snapshot-grade identity matcher and delegates source-type filtering,
primary-source ranking, destination-neutral source references, and notes to the
shared ``assemble_enrichment`` projection authority — the same projection
``/v1/enrich`` uses over its own pack-backed matcher, so the two surfaces agree for
the same decision and sources. These tests pin matched/ambiguous/no-match behaviour,
order and duplicate preservation, exact ``row_id`` echo, bounded inputs, schema
conformance, and that no internal path or advisory claim leaks.
"""

import json
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_mcp import tools  # noqa: E402
from openva_mcp.server import SPEC_BY_NAME, TOOL_SPECS  # noqa: E402
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot  # noqa: E402

from tests.test_agent_export import (  # noqa: E402
    build,
    make_repo,
    run_artifact,
    write_ledger_event,
    write_legal_entity,
)

ROW_SCHEMA = json.loads((ROOT / "schemas/openva/agent-enrichment-row.schema.json").read_text(encoding="utf-8"))
REQUEST_SCHEMA = json.loads((ROOT / "schemas/openva/agent-enrichment-request.schema.json").read_text(encoding="utf-8"))
RESULT_SCHEMA = json.loads((ROOT / "schemas/openva/agent-enrichment-result.schema.json").read_text(encoding="utf-8"))


@pytest.fixture
def snapshot(tmp_path) -> Snapshot:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    tree = build(tmp_path, latest_observations=run_artifact())
    return Snapshot.load(LocalSnapshotSource(tree))


class _FakeSnapshot:
    """Minimal in-memory snapshot for cases the single-vendor export fixture cannot
    express (ambiguous match, multiple sources of one type). Exposes exactly the
    surface ``enrich_inventory`` and the result envelope read."""

    mode = "pinned_local"
    commit_sha = "testsha0000000000000000000000000000000000"
    digest = "sha256:" + "0" * 64
    generated_at = "2026-06-12T00:00:00Z"
    from_cache = False

    def __init__(self, vendors, sources_by_vendor):
        self._vendors = vendors
        self._sources = sources_by_vendor

    def vendors_index(self):
        return {"vendors": self._vendors}

    def vendor_export(self, vendor_id):
        if any(v["vendor_id"] == vendor_id for v in self._vendors):
            return {"sources": self._sources.get(vendor_id, [])}
        return None


# --------------------------------------------------------------------------- match states


def test_matched_no_match_and_summary(snapshot):
    out = tools.enrich_inventory(
        snapshot,
        [{"row_id": "a", "domain": "vendor.example"}, {"row_id": "b", "domain": "unknown-co.tld"}],
    )
    matched = out["results"][0]
    no_match = out["results"][1]
    assert matched["match"]["status"] == "matched"
    assert matched["match"]["vendor_id"] == "example-vendor"
    assert matched["identity"] == {
        "match_status": "match",
        "matched_vendor_id": "example-vendor",
        "matched_vendor_name": "Example Vendor",
        "match_basis": ["domain_exact"],
        "no_match_reason": None,
    }
    assert no_match["match"]["status"] == "no_match"
    assert no_match["match"]["vendor_id"] is None
    assert no_match["identity"] == {
        "match_status": "no_match",
        "matched_vendor_id": None,
        "matched_vendor_name": None,
        "match_basis": [],
        "no_match_reason": "no_indexed_openva_match",
    }
    assert no_match["source_references"] == {}
    assert out["summary"] == {"matched": 1, "ambiguous": 0, "no_match": 1}
    assert out["count"] == 2
    assert out["not_advice"] is True
    assert out["snapshot"]["commit_sha"] == snapshot.commit_sha


def test_registration_number_matches_when_export_carries_legal_entity(tmp_path):
    # End-to-end over a real verified snapshot whose vendor export now carries a legal
    # entity: a registration-number-only row matches via the shared legal-entity fallback.
    make_repo(tmp_path)
    write_legal_entity(tmp_path, entity_id="example-vendor-le", registration_number="RC-555")
    snapshot = Snapshot.load(LocalSnapshotSource(build(tmp_path, latest_observations=run_artifact())))

    enriched = tools.enrich_inventory(snapshot, [{"row_id": "1", "registration_number": "RC-555"}], source_types=["dpa"])
    result = enriched["results"][0]
    assert result["match"]["status"] == "matched"
    assert result["match"]["vendor_id"] == "example-vendor"
    assert result["match"]["method"] == "registration_number_exact"
    assert result["identity"]["match_status"] == "match"
    assert result["identity"]["match_basis"] == ["registration_number_exact"]

    matched = tools.match_inventory(snapshot, [{"registration_number": "RC-555"}])
    assert matched["results"][0]["match_status"] == "matched"
    assert matched["results"][0]["matched_vendor_id"] == "example-vendor"

    # An unknown registration number still resolves to no_match.
    unknown = tools.enrich_inventory(snapshot, [{"row_id": "2", "registration_number": "RC-NOPE"}])
    assert unknown["results"][0]["match"]["status"] == "no_match"


def test_registration_number_no_match_without_legal_data(snapshot):
    # The default fixture export carries no legal entities -> registration-only no_match.
    out = tools.enrich_inventory(snapshot, [{"row_id": "1", "registration_number": "RC-555"}])
    assert out["results"][0]["match"]["status"] == "no_match"


def test_ambiguous_stays_ambiguous_and_projection_empty():
    vendors = [
        {"vendor_id": "acme-a", "canonical_name": "Acme Corp", "domains": []},
        {"vendor_id": "acme-b", "canonical_name": "Acme Corp", "domains": []},
    ]
    fake = _FakeSnapshot(vendors, {})
    out = tools.enrich_inventory(fake, [{"row_id": "1", "vendor_name": "Acme Corp"}])
    result = out["results"][0]
    assert result["match"]["status"] == "ambiguous"
    assert result["match"]["vendor_id"] is None
    assert result["identity"]["match_status"] == "no_match"
    assert result["identity"]["no_match_reason"] == "multiple_plausible_entities"
    assert {c["vendor_id"] for c in result["match"]["candidates"]} == {"acme-a", "acme-b"}
    assert result["sources"] == []
    assert result["source_references"] == {}
    assert result["primary_source_by_type"] == {}
    assert result["source_urls_by_type"] == {}
    assert result["notes"] == ["Ambiguous vendor match"]


# --------------------------------------------------------------------------- order / dupes / row_id


def test_order_duplicates_and_row_id_echo(snapshot):
    rows = [
        {"row_id": "12", "domain": "vendor.example"},
        {"row_id": 7, "domain": "vendor.example"},  # duplicate identity, integer row_id
        {"row_id": "x", "vendor_name": "Definitely Not A Vendor 9000"},
    ]
    out = tools.enrich_inventory(snapshot, rows)
    assert [r["row_id"] for r in out["results"]] == ["12", 7, "x"]  # exact echo, types intact
    assert out["results"][0]["match"]["vendor_id"] == "example-vendor"
    assert out["results"][1]["match"]["vendor_id"] == "example-vendor"
    assert out["results"][2]["match"]["status"] == "no_match"


# --------------------------------------------------------------------------- source-type filtering


def test_source_type_filter_and_missing_type_note(snapshot):
    out = tools.enrich_inventory(
        snapshot,
        [{"row_id": "1", "domain": "vendor.example"}],
        source_types=["dpa", "trust_center"],
    )
    result = out["results"][0]
    assert {s["source_type"] for s in result["sources"]} <= {"dpa", "trust_center"}
    assert "dpa" in result["primary_source_by_type"]
    assert result["source_urls_by_type"]["dpa"] == ["https://vendor.example/legal/dpa"]
    assert result["source_references"]["dpa"] == {
        "status": "indexed",
        "source_type": "dpa",
        "url": "https://vendor.example/legal/dpa",
        "title": None,
        "source_id": "example-dpa",
    }
    assert result["source_references"]["trust_center"] == {
        "status": "not_indexed",
        "source_type": "trust_center",
        "url": None,
        "title": None,
        "source_id": None,
    }
    assert "Matched vendor has no indexed trust centre source record" in result["notes"]


def test_unknown_source_type_yields_no_sources(snapshot):
    out = tools.enrich_inventory(snapshot, [{"row_id": "1", "domain": "vendor.example"}], source_types=["made_up_type"])
    result = out["results"][0]
    assert result["sources"] == []
    assert result["primary_source_by_type"] == {}
    assert result["source_references"]["made_up_type"]["status"] == "not_indexed"
    assert result["notes"] == ["Matched vendor has no indexed made_up_type source record"]


def test_primary_source_selection_is_deterministic_across_multiple():
    vendors = [{"vendor_id": "multi", "canonical_name": "Multi", "domains": ["multi.example"]}]
    sources = {
        "multi": [
            {"source_id": "s-late", "source_type": "dpa", "source_url": "https://multi.example/dpa-late", "effective_or_published_at": "2024-01-01"},
            {"source_id": "s-new", "source_type": "dpa", "source_url": "https://multi.example/dpa-new", "effective_or_published_at": "2026-01-01", "title": "New DPA"},
        ]
    }
    out = tools.enrich_inventory(_FakeSnapshot(vendors, sources), [{"row_id": "1", "domain": "multi.example"}], source_types=["dpa"])
    primary = out["results"][0]["primary_source_by_type"]["dpa"]
    assert primary["source_id"] == "s-new"  # newest effective date wins
    assert out["results"][0]["source_references"]["dpa"] == {
        "status": "indexed",
        "source_type": "dpa",
        "url": "https://multi.example/dpa-new",
        "title": None,
        "source_id": "s-new",
    }
    assert out["results"][0]["source_urls_by_type"]["dpa"] == [
        "https://multi.example/dpa-late",
        "https://multi.example/dpa-new",
    ]


# --------------------------------------------------------------------------- validation / bounds


def test_empty_identity_row_is_rejected(snapshot):
    with pytest.raises(ValueError):
        tools.enrich_inventory(snapshot, [{"row_id": "1"}])
    with pytest.raises(ValueError):
        tools.enrich_inventory(snapshot, [{"row_id": "1", "vendor_name": "  ", "domain": ""}])


def test_input_schema_bounds_rows_and_field_length():
    schema = SPEC_BY_NAME["enrich_inventory"].input_schema
    # Within bounds passes.
    jsonschema.validate({"rows": [{"row_id": "1", "vendor_name": "Stripe"}]}, schema)
    # Too many rows is rejected by the declared schema.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x"}] * 501}, schema)
    # Over-long identity field is rejected.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "z" * 513}]}, schema)
    # Unknown row field is rejected (no workspace columns leak in).
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x", "workspace_id": "abc"}]}, schema)
    # Too many source types is rejected.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x"}], "source_types": ["dpa"] * 65}, schema)


# --------------------------------------------------------------------------- schema conformance


def test_tool_output_conforms_to_result_schema(snapshot):
    out = tools.enrich_inventory(
        snapshot,
        [{"row_id": "1", "domain": "vendor.example"}, {"row_id": "2", "domain": "no.example"}],
        source_types=["dpa"],
    )
    for result in out["results"]:
        jsonschema.validate(result, RESULT_SCHEMA)


def test_request_schema_accepts_documented_mcp_example():
    # The request schema is the MCP envelope (top-level `rows`).
    example = {
        "rows": [
            {"row_id": "17", "vendor_name": "Stripe", "domain": "stripe.com", "business_entity_name": None, "registration_number": None}
        ],
        "source_types": ["dpa", "subprocessors_list", "privacy_notice", "security_page", "trust_center", "compliance_page"],
    }
    jsonschema.validate(example, REQUEST_SCHEMA)


def test_mcp_request_schema_is_transport_specific_not_v1_vendors():
    # The MCP request uses `rows`, so a /v1-style `{vendors: [...]}` payload is NOT
    # valid against it. This proves the schema is honestly transport-specific rather
    # than falsely claimed to validate both surfaces.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"vendors": [{"vendor_name": "Stripe"}]}, REQUEST_SCHEMA)


def test_shared_row_schema_accepts_both_surfaces_rows():
    # The genuinely shared contract is the row; both a /v1 `vendors[]` item and an MCP
    # `rows[]` item are the same row shape.
    for row in (
        {"row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com"},  # MCP rows[] item
        {"row_id": 7, "domain": "slack.com", "registration_number": "RC-1"},  # /v1 vendors[] item
    ):
        jsonschema.validate(row, ROW_SCHEMA)
    # The shared row also rejects unrelated workspace columns.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"vendor_name": "x", "spreadsheet_id": "abc"}, ROW_SCHEMA)


# --------------------------------------------------------------------------- no leakage / no advice


def test_no_internal_path_or_underscore_keys_leak(snapshot):
    out = tools.enrich_inventory(snapshot, [{"row_id": "1", "domain": "vendor.example"}], source_types=["dpa"])
    blob = json.dumps(out)
    assert "_openva_path" not in blob
    for result in out["results"]:
        for source in result["sources"]:
            assert all(not str(key).startswith("_") for key in source)


def test_no_advisory_claims_in_output(snapshot):
    out = tools.enrich_inventory(snapshot, [{"row_id": "1", "domain": "vendor.example"}])
    blob = json.dumps(out).lower()
    assert out["not_advice"] is True
    for banned in ("compliant", "approved", "risk score", "pass/fail", "suitable", "recommend"):
        assert banned not in blob


# --------------------------------------------------------------------------- registry


def test_enrich_inventory_registered_with_valid_schema():
    spec = SPEC_BY_NAME["enrich_inventory"]
    assert spec.input_schema["type"] == "object"
    assert "rows" in spec.input_schema["properties"]
    assert spec.description and callable(spec.func)
    assert spec in TOOL_SPECS


def _normalize_row(schema):
    """Structural view of a row schema for drift comparison: additionalProperties plus
    each property's type (order-insensitive) and maxLength. Descriptions/titles ignored."""

    def types(prop):
        declared = prop.get("type")
        return sorted(declared) if isinstance(declared, list) else [declared]

    return {
        "additionalProperties": schema.get("additionalProperties"),
        "properties": {
            name: {"type": types(prop), "maxLength": prop.get("maxLength")}
            for name, prop in schema.get("properties", {}).items()
        },
    }


def test_three_row_schema_definitions_do_not_drift():
    # The shared row is declared in three places; assert they are structurally equal so
    # the runtime tool schema and the published JSON Schemas cannot drift apart.
    from openva_mcp.server import _ENRICH_ROW_SCHEMA

    standalone = _normalize_row(ROW_SCHEMA)
    request_defs_row = _normalize_row(REQUEST_SCHEMA["$defs"]["row"])
    mcp_runtime_row = _normalize_row(_ENRICH_ROW_SCHEMA)
    assert standalone == request_defs_row == mcp_runtime_row
