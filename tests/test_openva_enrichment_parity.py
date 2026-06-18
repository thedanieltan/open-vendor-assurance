"""Cross-surface parity: MCP ``enrich_inventory`` vs match-service ``enrich_one``.

Both adapters delegate to the shared ``enrich_identity`` authority, so for the same
vendor identity and the same canonical sources they must agree on the parity-
relevant decisions: match status, matched vendor, candidate set, which source
types survive the filter, which source is primary per type, and the notes. The two
surfaces project per-source fields differently (snapshot vs pack), so only the
shared-decision fields are compared, not whole source objects.

This runs in the full suite (it imports both surfaces). It builds one logical
catalogue — the agent-export ``example-vendor`` tree for MCP, and an equivalent
in-memory ``MatcherIndex`` for the match service — with the same vendor, source
ids, types, and URLs, and asserts the decisions match.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
    ROOT / "services" / "openva_match_service",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_vendor_inventory_matcher.core import legal_entity_record, vendor_record  # noqa: E402
from openva_vendor_inventory_matcher.matcher import MatcherIndex  # noqa: E402

from openva_mcp import tools  # noqa: E402
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot  # noqa: E402
from openva_match_service.enrichment import enrich_one  # noqa: E402
from openva_match_service.service_state import PackMeta, ServiceState  # noqa: E402

from tests.test_agent_export import build, make_repo, run_artifact, write_ledger_event  # noqa: E402

# The match-service canonical-source rows for the same vendor as the export tree.
PACK_SOURCES = {
    "example-vendor": [
        {"source_id": "example-vendor-dpa", "source_type": "dpa", "source_url": "https://vendor.example/legal/dpa", "canonical": True},
        {"source_id": "example-vendor-privacy", "source_type": "privacy_notice", "source_url": "https://vendor.example/privacy", "canonical": True},
    ]
}


@pytest.fixture
def snapshot(tmp_path) -> Snapshot:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    return Snapshot.load(LocalSnapshotSource(build(tmp_path, latest_observations=run_artifact())))


def _service_state(vendors, sources_by_vendor) -> ServiceState:
    index = MatcherIndex(vendors, {}, sources_by_vendor, {}, {}, [], {})
    return ServiceState(
        pack=None,
        matcher_index=index,
        meta=PackMeta(profile_id="parity", schema_version="0.1.0", generated_at="2026-06-12T00:00:00Z", counts={}),
        snapshot_digest="sha256:" + "0" * 64,
        latest_observation_by_source={},
        guarantees={},
    )


def _example_state() -> ServiceState:
    return _service_state([vendor_record({"vendor_id": "example-vendor", "display_name": "Example Vendor", "official_domains": ["vendor.example"]})], PACK_SOURCES)


def _decision(result: dict) -> dict:
    """Extract only the parity-relevant decision fields from one enrichment result."""
    return {
        "status": result["match"]["status"],
        "vendor_id": result["match"]["vendor_id"],
        "method": result["match"]["method"],
        "candidates": sorted(c["vendor_id"] for c in result["match"]["candidates"]),
        "source_types": sorted({s["source_type"] for s in result["sources"]}),
        "primary_by_type": {k: v["source_id"] for k, v in result["primary_source_by_type"].items()},
        "urls_by_type": result["source_urls_by_type"],
        "notes": result["notes"],
    }


def _mcp(snapshot, identity, source_types):
    return tools.enrich_inventory(snapshot, [{"row_id": "1", **identity}], source_types=source_types)["results"][0]


def _http(state, identity, source_types):
    return enrich_one(state, row_id="1", source_types=source_types, **{
        "vendor_name": identity.get("vendor_name"),
        "domain": identity.get("domain"),
        "business_entity_name": identity.get("business_entity_name"),
        "registration_number": identity.get("registration_number"),
    })


def test_matched_decision_is_identical(snapshot):
    state = _example_state()
    identity = {"domain": "vendor.example"}
    source_types = ["dpa", "privacy_notice", "trust_center"]
    assert _decision(_mcp(snapshot, identity, source_types)) == _decision(_http(state, identity, source_types))


def test_matched_decision_identical_without_filter(snapshot):
    state = _example_state()
    identity = {"vendor_name": "Example Vendor"}
    assert _decision(_mcp(snapshot, identity, None)) == _decision(_http(state, identity, None))


def test_no_match_decision_is_identical(snapshot):
    state = _example_state()
    identity = {"vendor_name": "Definitely Not A Vendor 9000"}
    mcp = _decision(_mcp(snapshot, identity, ["dpa"]))
    http = _decision(_http(state, identity, ["dpa"]))
    assert mcp == http
    assert mcp["status"] == "no_match"
    assert mcp["notes"] == ["No catalogue match"]


def test_ambiguous_decision_is_identical():
    # No export-tree match needed: build equivalent two-vendor catalogues for both surfaces.
    vendors = [
        {"vendor_id": "acme-a", "canonical_name": "Acme Corp", "domains": []},
        {"vendor_id": "acme-b", "canonical_name": "Acme Corp", "domains": []},
    ]

    class _FakeSnapshot:
        mode = "pinned_local"
        commit_sha = "sha"
        digest = "sha256:" + "0" * 64
        generated_at = "2026-06-12T00:00:00Z"
        from_cache = False

        def vendors_index(self):
            return {"vendors": vendors}

        def vendor_export(self, vendor_id):
            return {"sources": []} if vendor_id in {"acme-a", "acme-b"} else None

    state = _service_state(
        [
            vendor_record({"vendor_id": "acme-a", "display_name": "Acme Corp", "legal_name": "Acme Corp"}),
            vendor_record({"vendor_id": "acme-b", "display_name": "Acme Corp", "legal_name": "Acme Corp"}),
        ],
        {},
    )
    identity = {"vendor_name": "Acme Corp"}
    mcp = _decision(_mcp(_FakeSnapshot(), identity, ["dpa"]))
    http = _decision(_http(state, identity, ["dpa"]))
    assert mcp == http
    assert mcp["status"] == "ambiguous"
    assert mcp["notes"] == ["Ambiguous vendor match"]


def test_registration_number_is_the_documented_parity_boundary():
    """The honest boundary: matcher capability follows the data each surface holds.

    The match service runs the pack-backed matcher with legal-entity data, so a
    registration-number-only row matches. The MCP snapshot carries no legal-entity
    data, so the same row is no_match. The shared *projection* is identical; the
    *matcher* differs by capability, and that difference is intentional, not a
    regression of the HTTP contract.
    """
    # HTTP surface: vendor reachable only via its legal entity's registration number.
    vendor = vendor_record({"vendor_id": "regco", "display_name": "Reg Co", "legal_name": "Reg Co Limited", "official_domains": ["regco.example"]})
    entity = legal_entity_record({"entity_id": "regco-le", "vendor_id": "regco", "legal_name": "Reg Co Limited", "jurisdiction": "GB", "registration_number": "RC-987654", "catalog_status": "active"})
    http_state = ServiceState(
        pack=None,
        matcher_index=MatcherIndex([vendor], {}, {"regco": []}, {}, {}, [entity], {}),
        meta=PackMeta(profile_id="parity", schema_version="0.1.0", generated_at="2026-06-12T00:00:00Z", counts={}),
        snapshot_digest="sha256:" + "0" * 64,
        latest_observation_by_source={},
        guarantees={},
    )
    http = _http(http_state, {"registration_number": "RC-987654"}, ["dpa"])
    assert http["match"]["status"] == "matched"
    assert http["match"]["vendor_id"] == "regco"

    # MCP surface: same vendor present, but the snapshot has no legal-entity data.
    class _FakeSnapshot:
        mode = "pinned_local"
        commit_sha = "sha"
        digest = "sha256:" + "0" * 64
        generated_at = "2026-06-12T00:00:00Z"
        from_cache = False

        def vendors_index(self):
            return {"vendors": [{"vendor_id": "regco", "canonical_name": "Reg Co", "domains": ["regco.example"]}]}

        def vendor_export(self, vendor_id):
            return {"sources": []} if vendor_id == "regco" else None

    mcp = _mcp(_FakeSnapshot(), {"registration_number": "RC-987654"}, ["dpa"])
    assert mcp["match"]["status"] == "no_match"


def test_duplicate_rows_and_order_preserved_identically(snapshot):
    rows = [
        {"row_id": "a", "domain": "vendor.example"},
        {"row_id": "a", "domain": "vendor.example"},
        {"row_id": "b", "vendor_name": "Nope Nope 9000"},
    ]
    mcp_results = tools.enrich_inventory(snapshot, rows, source_types=["dpa"])["results"]
    state = _example_state()
    http_results = [
        enrich_one(
            state,
            row_id=row["row_id"],
            vendor_name=row.get("vendor_name"),
            domain=row.get("domain"),
            business_entity_name=None,
            registration_number=None,
            source_types=["dpa"],
        )
        for row in rows
    ]
    assert [r["row_id"] for r in mcp_results] == [r["row_id"] for r in http_results] == ["a", "a", "b"]
    assert [_decision(r) for r in mcp_results] == [_decision(r) for r in http_results]
