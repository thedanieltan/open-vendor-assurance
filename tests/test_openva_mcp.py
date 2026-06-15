"""Tests for the read-only OpenVA MCP core (snapshot + tools).

The MCP package lives outside the repo's importable tree, so its source dir is
added to sys.path here. The export tree under test is produced by the real
agent_export builder, so these tests also pin the MCP adapter to the live
export contract.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MCP_SRC = ROOT / "integrations" / "mcp" / "openva_mcp"
MATCHER_SRC = ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher"
PACK_READER_SRC = ROOT / "adapters" / "python" / "openva_pack_reader"
for _src in (MCP_SRC, MATCHER_SRC, PACK_READER_SRC):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_mcp import tools  # noqa: E402
from openva_mcp.snapshot import (  # noqa: E402
    LocalSnapshotSource,
    RemoteSnapshotSource,
    Snapshot,
    SnapshotIntegrityError,
    SnapshotUnsupportedSchemaError,
)

from tests.test_agent_export import (  # noqa: E402
    COMMIT_SHA,
    build,
    make_repo,
    run_artifact,
    freshness_artifact,
    write_ledger_event,
)


@pytest.fixture
def export_tree(tmp_path) -> Path:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    return build(
        tmp_path,
        latest_observations=run_artifact(),
        freshness_report=freshness_artifact(),
    )


@pytest.fixture
def snapshot(export_tree) -> Snapshot:
    return Snapshot.load(LocalSnapshotSource(export_tree))


def test_load_verifies_root_index_self_digest(snapshot):
    assert snapshot.commit_sha == COMMIT_SHA
    assert snapshot.digest.startswith("sha256:")
    assert snapshot.mode == "pinned_local"


def test_search_vendors_finds_and_filters(snapshot):
    result = tools.search_vendors(snapshot)
    assert result["count"] >= 1
    assert any(v["vendor_id"] == "example-vendor" for v in result["vendors"])
    assert result["not_advice"] is True

    filtered = tools.search_vendors(snapshot, query="example")
    assert all("example" in v["vendor_id"] for v in filtered["vendors"])
    empty = tools.search_vendors(snapshot, query="no-such-vendor")
    assert empty["count"] == 0


def test_get_vendor_and_sources_preserve_original_urls(snapshot):
    vendor = tools.get_vendor(snapshot, "example-vendor")
    assert vendor["found"] is True
    assert vendor["vendor"]["vendor_id"] == "example-vendor"

    sources = tools.list_vendor_sources(snapshot, "example-vendor")
    urls = {s["source_url"] for s in sources["sources"]}
    assert "https://vendor.example/legal/dpa" in urls
    for source in sources["sources"]:
        assert source["vendor_id"] == "example-vendor"
        assert source["source_id"]
        assert source["source_url"]


def test_unmatched_vendor_stays_unmatched(snapshot):
    result = tools.get_vendor(snapshot, "does-not-exist")
    assert result["found"] is False
    assert result["vendor"] is None


def test_get_source_and_health(snapshot):
    source = tools.get_source(snapshot, "example-vendor-dpa")
    assert source["found"] is True
    assert source["source"]["source_url"] == "https://vendor.example/legal/dpa"

    health = tools.get_source_health(snapshot, "example-vendor-dpa")
    assert health["found"] is True
    assert health["source_health"] == "reachable"
    assert health["last_observed_at"] == "2026-06-10T05:30:00Z"
    assert health["observation_input"] == "run_artifact"

    missing = tools.get_source(snapshot, "no-source")
    assert missing["found"] is False


def test_get_vendor_changes(snapshot):
    changes = tools.get_vendor_changes(snapshot, "example-vendor")
    assert changes["count"] >= 1
    assert all(c["vendor_id"] == "example-vendor" for c in changes["changes"])


def test_match_inventory_matched_ambiguous_unmatched(snapshot):
    rows = [
        {"domain": "vendor.example"},
        {"vendor_name": "Example Vendor"},
        {"domain": "unknown-company.tld"},
    ]
    result = tools.match_inventory(snapshot, rows)
    by_status = [r["match_status"] for r in result["results"]]
    assert by_status[0] == "matched"
    assert result["results"][0]["matched_vendor_id"] == "example-vendor"
    assert by_status[2] == "no_match"
    assert result["results"][2]["matched_vendor_id"] is None
    assert result["summary"]["matched"] >= 1


def test_every_source_result_carries_snapshot_identity_and_not_advice(snapshot):
    for result in (
        tools.list_vendor_sources(snapshot, "example-vendor"),
        tools.get_source(snapshot, "example-vendor-dpa"),
        tools.get_source_health(snapshot, "example-vendor-dpa"),
        tools.get_vendor_changes(snapshot, "example-vendor"),
    ):
        assert result["not_advice"] is True
        assert result["snapshot"]["commit_sha"] == COMMIT_SHA
        assert result["snapshot"]["digest"].startswith("sha256:")


def test_verify_snapshot_reports_ok(snapshot):
    report = tools.verify_snapshot(snapshot)["verification"]
    assert report["ok"] is True
    assert all(f["match"] for f in report["files"])
    assert report["commit_sha"] == COMMIT_SHA


def test_tampered_export_fails_closed(export_tree):
    target = export_tree / "vendors" / "example-vendor.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["domains"] = ["tampered.example"]  # mutate payload, leave digest stale
    target.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")

    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    with pytest.raises(SnapshotIntegrityError):
        snapshot.vendor_export("example-vendor")
    assert tools.verify_snapshot(snapshot)["verification"]["ok"] is False


def test_tampered_root_index_fails_to_load(export_tree):
    target = export_tree / "openva-agent-index.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["counts"] = {"vendors": 999, "sources": 999}
    target.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError):
        Snapshot.load(LocalSnapshotSource(export_tree))


def test_unsupported_schema_version_is_rejected(export_tree):
    target = export_tree / "openva-agent-index.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["schema_version"] = "9.9.9"
    target.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(SnapshotUnsupportedSchemaError):
        Snapshot.load(LocalSnapshotSource(export_tree))


def test_remote_cached_fallback_is_disclosed(export_tree):
    # First serve from "remote" (a fetch that reads the built tree) to populate
    # the cache, then make the network fail and confirm cache use is disclosed.
    def reader(url: str) -> bytes:
        rel = url.split("openva-tree/", 1)[1]
        return (export_tree / rel).read_bytes()

    def failing(url: str) -> bytes:
        raise OSError("network down")

    cache = export_tree.parent / "cache"
    warm = RemoteSnapshotSource("https://host/openva-tree/", fetch=reader, cache_dir=cache)
    snapshot = Snapshot.load(warm)
    snapshot.vendors_index()
    assert snapshot.from_cache is False

    cold = RemoteSnapshotSource("https://host/openva-tree/", fetch=failing, cache_dir=cache)
    cached_snapshot = Snapshot.load(cold)
    assert cached_snapshot.from_cache is True
    assert cached_snapshot.provenance()["from_cache"] is True
    assert cached_snapshot.commit_sha == COMMIT_SHA


def test_no_mutation_or_advisory_tools_are_exposed():
    from openva_mcp.server import TOOL_SPECS

    names = {name for name in dir(tools) if not name.startswith("_")}
    names |= {spec.name for spec in TOOL_SPECS}
    forbidden = {
        "create",
        "update",
        "delete",
        "approve",
        "reject",
        "promote",
        "score",
        "rank",
        "risk",
        "write",
        "push",
        "merge",
        "recommend",
    }
    assert not any(any(bad in name.lower() for bad in forbidden) for name in names), names


def test_tool_specs_cover_required_tools_with_valid_schemas():
    from openva_mcp.server import TOOL_SPECS

    required = {
        "search_vendors",
        "get_vendor",
        "list_vendor_sources",
        "get_source",
        "get_source_health",
        "get_vendor_changes",
        "match_inventory",
        "get_snapshot_metadata",
        "verify_snapshot",
    }
    names = {spec.name for spec in TOOL_SPECS}
    assert required.issubset(names)
    for spec in TOOL_SPECS:
        assert spec.input_schema["type"] == "object"
        assert spec.description
        assert callable(spec.func)


def test_tool_specs_dispatch_through_func(snapshot):
    from openva_mcp.server import TOOL_SPECS

    by_name = {spec.name: spec for spec in TOOL_SPECS}
    result = by_name["get_vendor"].func(snapshot, {"vendor_id": "example-vendor"})
    assert result["found"] is True
    assert result["not_advice"] is True


def test_resolve_snapshot_requires_a_data_mode():
    import argparse

    from openva_mcp.server import resolve_snapshot

    args = argparse.Namespace(snapshot=None, base_url=None, cache_dir=None)
    with pytest.raises(SystemExit):
        resolve_snapshot(args)


def test_mcp_server_builds_when_sdk_present(snapshot):
    pytest.importorskip("mcp.server.fastmcp")
    from openva_mcp.server import build_server

    server = build_server(snapshot)
    assert server is not None
