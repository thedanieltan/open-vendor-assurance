"""Ratification audit for the legal-entity export + matching enhancement.

WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01. The legal-entity export/matching change set
reached `main` MERGED_BUT_UNRATIFIED: PR #400 (candidate-activation) inherited commit
26b2922 and its squash bundled the legal-entity work in without independent review of
*that* change set. These tests are the adversarial/parity/regression evidence that the
bundled functionality is sound, and they lock the audited invariants against
regression. (Evidence narrative: docs/operations/legal-entity-export-ratification.md.)

The change set under audit (16 files, == commit 26b2922):
  core.select_with_legal_fallback + matcher.enrich_row refactor; enrichment.match_identity
  legal fallback; openva_mcp matching/tools/server; agent_export legal_entities projection;
  agent-export + agent-enrichment-row schemas; ADR-0003 + agent-workspace-composition docs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_vendor_inventory_matcher.core import (  # noqa: E402
    group_legal_entities_by_registration,
    legal_entity_record,
    match_candidates,
    select_with_legal_fallback,
    vendor_record,
)

from tools.openva.advisory_wording import load_prohibited_terms  # noqa: E402
from tools.openva.release_gates import (  # noqa: E402
    find_advisory_terms,
    find_digest_mismatches,
    find_missing_non_advisory_doctrine,
    find_self_certifying_or_private_leaks,
)

from tests.test_agent_export import (  # noqa: E402
    build,
    make_repo,
    run_artifact,
    write_ledger_event,
    write_legal_entity,
)

AGENT_SCHEMA = json.loads((ROOT / "schemas/openva/agent-export.schema.json").read_text(encoding="utf-8"))
EXPORT_FILES = [
    "openva-agent-index.json",
    "vendors/index.json",
    "vendors/example-vendor.json",
    "sources/index.json",
    "observations/latest.json",
    "changes/latest.json",
]


def _def_for(rel: str) -> str:
    return {
        "openva-agent-index.json": "agent_index",
        "vendors/index.json": "vendors_index",
        "sources/index.json": "sources_index",
        "observations/latest.json": "observations_latest",
        "changes/latest.json": "changes_latest",
    }.get(rel, "vendor_export")


LEGAL_ENTITY_SCHEMA = json.loads((ROOT / "schemas/openva/legal-entity.schema.json").read_text(encoding="utf-8"))

# A VERIFIED (canonical) legal-entity record whose verification and registered-address
# evidence reference a real source the fixture vendor carries (example-vendor-dpa, created
# by make_repo). It is valid under the RAW legal-entity schema — establishing that the
# exported metadata is public-source-backed, not merely schema-shaped.
_CANONICAL_ENTITY_YAML = (
    "schema_version: 0.1.0\n"
    "entity_id: example-vendor-le\n"
    "vendor_id: example-vendor\n"
    "legal_name: Example Vendor Ltd\n"
    "jurisdiction: GB\n"
    "registration_number: RC-555123\n"
    "verification_source_ids:\n"
    "  - example-vendor-dpa\n"
    "catalog_status: canonical\n"
    "registered_address:\n"
    "  address_lines:\n"
    "    - 1 Example Way\n"
    "  locality: London\n"
    "  country: GB\n"
    "  source_ids:\n"
    "    - example-vendor-dpa\n"
    "not_advice: true\n"
)


def _write_entity_with_address(tmp_path: Path) -> None:
    entity_dir = tmp_path / "data" / "vendors" / "example-vendor" / "legal_entities"
    entity_dir.mkdir(parents=True, exist_ok=True)
    (entity_dir / "example-vendor-le.yaml").write_text(_CANONICAL_ENTITY_YAML, encoding="utf-8")


def _build_with_legal_entity(tmp_path: Path, out_name: str = "out") -> Path:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    _write_entity_with_address(tmp_path)
    return build(tmp_path, out_name=out_name, latest_observations=run_artifact())


def _docs(out: Path) -> dict[str, dict]:
    return {rel: json.loads((out / rel).read_text(encoding="utf-8")) for rel in EXPORT_FILES}


# --- export surface: public, non-advisory, deterministic ----------------------


def test_legal_entity_export_passes_all_release_gate_scanners(tmp_path):
    # Property: legal-entity metadata is public-source-backed and non-advisory, and
    # introduces no private/self-certifying leakage (even the nested registered_address).
    docs = _docs(_build_with_legal_entity(tmp_path))
    assert find_self_certifying_or_private_leaks(docs) == []
    assert find_advisory_terms(docs, load_prohibited_terms()) == []
    assert find_missing_non_advisory_doctrine(docs) == []
    assert find_digest_mismatches(docs, docs["openva-agent-index.json"]) == []


def test_legal_entity_export_validates_against_agent_export_schema(tmp_path):
    docs = _docs(_build_with_legal_entity(tmp_path))
    for rel, doc in docs.items():
        jsonschema.validate(doc, {"$ref": f"#/$defs/{_def_for(rel)}", "$defs": AGENT_SCHEMA["$defs"]})
    entities = docs["vendors/example-vendor.json"]["legal_entities"]
    assert {e["entity_id"] for e in entities} == {"example-vendor-le"}
    assert entities[0]["registration_number"] == "RC-555123"
    assert entities[0]["registered_address"]["country"] == "GB"


def test_legal_entity_export_is_build_twice_deterministic(tmp_path):
    out_a = _build_with_legal_entity(tmp_path, out_name="a")
    out_b = build(tmp_path, out_name="b", latest_observations=run_artifact())  # same inputs
    a = (out_a / "vendors/example-vendor.json").read_bytes()
    b = (out_b / "vendors/example-vendor.json").read_bytes()
    assert a == b, "legal-entity-bearing vendor export must be byte-identical across builds"


def test_vendor_without_legal_entities_is_backward_compatible(tmp_path):
    # No legal_entities/ directory -> the export must not carry the optional key, so
    # the entire shipped catalogue (which has none) is byte-identical to before.
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    out = build(tmp_path, latest_observations=run_artifact())
    vendor = json.loads((out / "vendors/example-vendor.json").read_text(encoding="utf-8"))
    assert "legal_entities" not in vendor


def test_exported_entity_is_valid_under_the_raw_legal_entity_schema():
    # Property 7 (public-source-backed): the exported entity is a VALID canonical
    # legal-entity record under the RAW schema — it carries verification source ids and
    # registered-address source ids, so the export is source-backed, not just shaped.
    record = yaml.safe_load(_CANONICAL_ENTITY_YAML)
    jsonschema.validate(record, LEGAL_ENTITY_SCHEMA)
    assert record["catalog_status"] == "canonical"
    assert record["verification_source_ids"] == ["example-vendor-dpa"]
    assert record["registered_address"]["source_ids"] == ["example-vendor-dpa"]


def test_unverified_stub_entities_are_not_exported(tmp_path):
    # Property 7: only verified (canonical) entities are exported; an unverified stub
    # must be excluded so the public_sources_only guarantee stays honest.
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    write_legal_entity(tmp_path, entity_id="example-vendor-stub", registration_number="RC-STUB", catalog_status="stub")
    out = build(tmp_path, latest_observations=run_artifact())
    vendor = json.loads((out / "vendors/example-vendor.json").read_text(encoding="utf-8"))
    assert "legal_entities" not in vendor, "an unverified stub legal entity must not be exported"


# --- registration matching: safety / fail-closed ------------------------------


def _vendors():
    return [
        vendor_record({"vendor_id": "acme", "display_name": "Acme", "official_domains": ["acme.example"]}),
        vendor_record({"vendor_id": "beta", "display_name": "Beta", "official_domains": ["beta.example"]}),
    ]


def _indexes(entity_rows):
    entities = [legal_entity_record(r) for r in entity_rows]
    return group_legal_entities_by_registration(entities), {e.entity_id: e for e in entities}


def _resolve(vendors, row, by_reg, by_id):
    candidates = match_candidates(vendors, "", "")  # registration-only (no domain/name)
    vendors_by_id = {v.vendor_id: v for v in vendors}
    selected, resolution = select_with_legal_fallback(
        vendors_by_id, candidates, row, by_registration=by_reg, by_id=by_id, contracting_by_key={}
    )
    return (selected.vendor.vendor_id if selected else None), resolution


SINGLE = [{"entity_id": "acme-le", "vendor_id": "acme", "legal_name": "Acme Ltd", "jurisdiction": "GB", "registration_number": "RC-555123", "catalog_status": "stub"}]


@pytest.mark.parametrize(
    "registration",
    ["", "   ", "ZZ-000-UNKNOWN"],
)
def test_no_false_positive_on_empty_or_unknown_registration(registration):
    by_reg, by_id = _indexes(SINGLE)
    vendor_id, _ = _resolve(_vendors(), {"registration_number": registration, "jurisdiction": ""}, by_reg, by_id)
    assert vendor_id is None, f"registration {registration!r} must not match any vendor"


def test_true_positive_and_normalisation_are_consistent():
    by_reg, by_id = _indexes(SINGLE)
    for registration in ("RC-555123", "rc555123", "RC 555123"):
        vendor_id, _ = _resolve(_vendors(), {"registration_number": registration, "jurisdiction": ""}, by_reg, by_id)
        assert vendor_id == "acme", f"{registration!r} should resolve to acme via the shared normalisation"


def test_ambiguous_registration_fails_closed_and_jurisdiction_disambiguates():
    # Two vendors share a registration number -> a registration-only row must NOT pick
    # one (fail closed); supplying the jurisdiction deterministically disambiguates.
    by_reg, by_id = _indexes([
        {"entity_id": "a-le", "vendor_id": "acme", "legal_name": "Acme Ltd", "jurisdiction": "GB", "registration_number": "DUP-1", "catalog_status": "stub"},
        {"entity_id": "b-le", "vendor_id": "beta", "legal_name": "Beta Ltd", "jurisdiction": "US", "registration_number": "DUP-1", "catalog_status": "stub"},
    ])
    vendor_id, resolution = _resolve(_vendors(), {"registration_number": "DUP-1", "jurisdiction": ""}, by_reg, by_id)
    assert vendor_id is None and resolution.confidence == "ambiguous", "ambiguous registration must fail closed"
    vendor_id_gb, _ = _resolve(_vendors(), {"registration_number": "DUP-1", "jurisdiction": "GB"}, by_reg, by_id)
    assert vendor_id_gb == "acme", "jurisdiction must deterministically disambiguate"


def test_entity_pointing_at_absent_vendor_is_a_safe_no_match():
    by_reg, by_id = _indexes([
        {"entity_id": "o-le", "vendor_id": "ghost", "legal_name": "Ghost", "jurisdiction": "GB", "registration_number": "GH-1", "catalog_status": "stub"},
    ])
    vendor_id, _ = _resolve(_vendors(), {"registration_number": "GH-1", "jurisdiction": ""}, by_reg, by_id)
    assert vendor_id is None, "a legal entity referencing an absent vendor must never synthesise a match"


def test_empty_legal_index_preserves_pre_enhancement_behaviour():
    vendor_id, resolution = _resolve(_vendors(), {"registration_number": "RC-555123", "jurisdiction": ""}, {}, {})
    assert vendor_id is None and resolution.method == "unresolved"


def test_conflicting_domain_and_registration_fails_closed_in_core():
    # Finding 2: domain/name -> vendor A, registration -> vendor B's entity. The shared
    # core must fail closed: neither attribute to A nor cross-link B's entity.
    from openva_vendor_inventory_matcher.core import normalize_domain

    by_reg, by_id = _indexes([
        {"entity_id": "beta-le", "vendor_id": "beta", "legal_name": "Beta Ltd", "jurisdiction": "US", "registration_number": "RC-BETA", "catalog_status": "canonical"},
    ])
    vendors = _vendors()
    candidates = match_candidates(vendors, normalize_domain("acme.example"), "")  # selects acme
    vendors_by_id = {v.vendor_id: v for v in vendors}
    selected, resolution = select_with_legal_fallback(
        vendors_by_id, candidates,
        {"registration_number": "RC-BETA", "jurisdiction": ""},
        by_registration=by_reg, by_id=by_id, contracting_by_key={},
    )
    assert selected is None, "must not attribute to vendor A when the registration belongs to vendor B"
    assert resolution.method == "registration_vendor_conflict"
    assert resolution.matched_entity is None, "must not cross-link vendor B's entity"


def test_conflicting_evidence_is_not_a_match_on_the_mcp_surface():
    # Same conflict via the MCP adapter: ambiguous (no matched vendor), conflict noted,
    # no cross-linked legal entity id.
    from openva_mcp import matching as mcp_matching

    by_reg, by_id = _indexes([
        {"entity_id": "beta-le", "vendor_id": "beta", "legal_name": "Beta Ltd", "jurisdiction": "US", "registration_number": "RC-BETA", "catalog_status": "canonical"},
    ])
    vendor_rows = [
        {"vendor_id": "acme", "canonical_name": "Acme", "domains": ["acme.example"]},
        {"vendor_id": "beta", "canonical_name": "Beta", "domains": ["beta.example"]},
    ]
    out = mcp_matching.match_row(
        vendor_rows,
        {"domain": "acme.example", "registration_number": "RC-BETA"},
        legal_by_registration=by_reg, legal_by_id=by_id,
    )
    assert out["matched_vendor_id"] is None
    assert out["match_status"] == "ambiguous"
    assert out["legal_entity_resolution"]["method"] == "registration_vendor_conflict"
    assert out["legal_entity_resolution"]["matched_entity_id"] is None


def test_consistent_domain_and_registration_still_matches():
    # The complement: when registration resolves to the SAME vendor the domain selects,
    # the match stands (no false negative from the conflict guard).
    from openva_vendor_inventory_matcher.core import normalize_domain

    by_reg, by_id = _indexes([
        {"entity_id": "acme-le", "vendor_id": "acme", "legal_name": "Acme Ltd", "jurisdiction": "GB", "registration_number": "RC-ACME", "catalog_status": "canonical"},
    ])
    vendors = _vendors()
    candidates = match_candidates(vendors, normalize_domain("acme.example"), "")
    selected, _ = select_with_legal_fallback(
        {v.vendor_id: v for v in vendors}, candidates,
        {"registration_number": "RC-ACME", "jurisdiction": ""},
        by_registration=by_reg, by_id=by_id, contracting_by_key={},
    )
    assert selected is not None and selected.vendor.vendor_id == "acme"


# --- cross-surface consistency + no new authority -----------------------------


def test_snapshot_and_pack_share_one_registration_authority():
    # The MCP/snapshot matcher and the pack matcher must call the SAME core fallback,
    # not a fork — the property that keeps the surfaces behaviourally consistent.
    from openva_mcp import matching as mcp_matching
    from openva_vendor_inventory_matcher import core, matcher

    assert mcp_matching.select_with_legal_fallback is core.select_with_legal_fallback
    assert matcher.select_with_legal_fallback is core.select_with_legal_fallback


def test_legal_entity_enhancement_added_no_write_tool_or_authority():
    # Audit property: no new catalogue mutation path or authority lane. The MCP tool
    # surface stays the read-only set (legal-entity added no tool), and the pure
    # matching modules carry no catalogue-write / authority / automerge coupling. (The
    # agent-export builder legitimately reads data/ and writes only the ephemeral out
    # tree; that read-only projection is exercised by the gate/determinism tests above.)
    from openva_mcp.server import TOOL_SPECS

    names = {spec.name for spec in TOOL_SPECS}
    write_verbs = ("create", "update", "delete", "promote", "write", "push", "merge", "approve", "submit")
    assert not any(any(verb in name for verb in write_verbs) for name in names), names
    for rel in (
        "adapters/python/openva_vendor_inventory_matcher/openva_vendor_inventory_matcher/core.py",
        "integrations/mcp/openva_mcp/openva_mcp/matching.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in ("data/vendors", "automerge", "bot-authority", "candidate_intake", "subprocess"):
            assert token not in text, f"{rel} unexpectedly references {token!r}"
