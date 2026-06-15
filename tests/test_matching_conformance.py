"""Cross-adapter matching conformance.

The CSV adapter (``openva_vendor_inventory_matcher.matcher``) and the MCP adapter
(``openva_mcp.matching``) must reach the same matching decision because they call
the same core. These tests assert agreement on status, vendor id, confidence,
method, and candidate identities for evidence both adapters carry, and assert
the legal-entity resolution is the shared core's, not a fork.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_mcp import matching as mcp_matching  # noqa: E402
from openva_vendor_inventory_matcher import core, matcher  # noqa: E402

from tests.test_openva_vendor_inventory_matcher import SyntheticPack, synthetic_vendor  # noqa: E402


def _csv_decision(index: matcher.MatcherIndex, row: dict) -> tuple:
    out = index.enrich_row(dict(row))
    candidate_ids = [c["vendor_id"] for c in json.loads(out["candidate_matches_json"])]
    confidence = float(out["match_confidence"]) if out["match_confidence"] else None
    return (
        out["match_status"],
        out["matched_vendor_id"] or None,
        confidence,
        out["match_method"] or None,
        candidate_ids,
        out["legal_entity_match_method"],
        out["legal_entity_resolution_confidence"],
    )


def _mcp_decision(vendor_rows: list[dict], row: dict) -> tuple:
    out = mcp_matching.match_row(vendor_rows, dict(row))
    return (
        out["match_status"],
        out["matched_vendor_id"],
        out["match_confidence"],
        out["match_method"],
        [c["vendor_id"] for c in out["candidates"]],
        out["legal_entity_resolution"]["method"],
        out["legal_entity_resolution"]["confidence"],
    )


def _mcp_rows(pack: SyntheticPack) -> list[dict]:
    # Agent-export vendor-index row shape (no legal_name, as the hosted export
    # genuinely carries none).
    return [
        {
            "vendor_id": v["vendor_id"],
            "canonical_name": v["display_name"],
            "domains": v["official_domains"],
            "catalog_status": v["catalog_status"],
            "source_count": 0,
            "export_path": f"vendors/{v['vendor_id']}.json",
        }
        for v in pack.vendor_search()
    ]


def _shared_evidence_pack() -> SyntheticPack:
    return SyntheticPack(
        [
            synthetic_vendor("acme", "Acme", ["acme.example"]),
            synthetic_vendor("beta", "Beta", ["beta.example"]),
            synthetic_vendor("shared-a", "Shared Name", ["shared-a.example"]),
            synthetic_vendor("shared-b", "Shared Name", ["shared-b.example"]),
        ]
    )


def test_adapters_agree_for_shared_evidence_inputs():
    pack = _shared_evidence_pack()
    index = matcher.MatcherIndex.from_pack(pack)
    vendor_rows = _mcp_rows(pack)

    inputs = [
        {"domain": "acme.example"},          # domain_exact
        {"domain": "app.acme.example"},      # domain_subdomain
        {"vendor_name": "Acme"},             # name_exact (display name)
        {"vendor_name": "Shared Name"},      # ambiguous
        {"domain": "nope.example"},          # no_match
    ]
    for row in inputs:
        assert _csv_decision(index, row) == _mcp_decision(vendor_rows, row), row


def test_legal_entity_resolution_uses_the_shared_core():
    pack = SyntheticPack.with_legal_entities()
    index = matcher.MatcherIndex.from_pack(pack)
    row = {"registration_number": "202012345A", "jurisdiction": "SG"}

    csv_decision = _csv_decision(index, row)
    # The CSV adapter resolves via the same core function, computed here directly.
    resolution = core.resolve_legal_entity(
        row,
        None,
        by_registration=index.legal_entities_by_registration,
        by_id=index.legal_entities_by_id,
        contracting_by_key=index.contracting_resolution_by_key,
    )
    assert csv_decision[5] == resolution.method == "registration_number_exact"
    assert csv_decision[6] == resolution.confidence == "matched"

    # The MCP adapter imports the same core function; with no legal-entity data
    # in the hosted export it resolves to unresolved (the core's empty result).
    assert mcp_matching.resolve_legal_entity is core.resolve_legal_entity
    mcp_out = mcp_matching.match_row(_mcp_rows(pack), row)
    assert mcp_out["legal_entity_resolution"]["method"] == "unresolved"


def test_mcp_matching_has_no_independent_rules():
    import inspect

    source = inspect.getsource(mcp_matching)
    # Thresholds and normalization live only in the core, not duplicated here.
    assert "MINIMUM_MATCH_CONFIDENCE" not in source
    assert "AMBIGUITY_MARGIN" not in source
    assert "from openva_vendor_inventory_matcher.core import" in source
