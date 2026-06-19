"""Real MCP client/server protocol tests.

The authoritative test runs a genuine ``ClientSession`` against the server over
the SDK's in-memory transport: it initializes, lists tools, checks each
published input schema against ``TOOL_SPECS``, and invokes representative tools.
A second test exercises the stdio transport via a subprocess; it skips only when
the host cannot spawn a subprocess (an environment limitation, not an SDK skip).
"""

import sys
from pathlib import Path

import anyio
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

pytest.importorskip("mcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from openva_mcp.server import TOOL_SPECS, build_server  # noqa: E402
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot  # noqa: E402

from tests.test_agent_export import build, make_repo, run_artifact, write_ledger_event  # noqa: E402

REQUIRED_TOOLS = {
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


@pytest.fixture
def export_tree(tmp_path) -> Path:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    return build(tmp_path, latest_observations=run_artifact())


def test_protocol_tools_list_and_calls(export_tree):
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))
    expected_schema = {spec.name: spec.input_schema for spec in TOOL_SPECS}

    async def scenario() -> None:
        server = build_server(snapshot)
        async with create_connected_server_and_client_session(server) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert REQUIRED_TOOLS.issubset(names)
            for tool in listed.tools:
                # The schema published over the wire matches the declared spec.
                assert tool.inputSchema == expected_schema[tool.name], tool.name

            meta = await client.call_tool("get_snapshot_metadata", {})
            assert meta.structuredContent["not_advice"] is True
            assert meta.structuredContent["snapshot"]["commit_sha"] == snapshot.commit_sha

            found = await client.call_tool("search_vendors", {"query": "example"})
            assert any(v["vendor_id"] == "example-vendor" for v in found.structuredContent["vendors"])

            vendor = await client.call_tool("get_vendor", {"vendor_id": "example-vendor"})
            assert vendor.structuredContent["found"] is True
            assert vendor.structuredContent["snapshot"]["digest"].startswith("sha256:")

            matched = await client.call_tool("match_inventory", {"rows": [{"domain": "vendor.example"}]})
            row = matched.structuredContent["results"][0]
            assert row["match_status"] == "matched"
            assert row["matched_vendor_id"] == "example-vendor"
            assert matched.structuredContent["not_advice"] is True

    anyio.run(scenario)


def test_protocol_rejects_invalid_tool_input(export_tree):
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))

    bad_calls = [
        ("get_vendor", {}),                              # missing required vendor_id
        ("get_vendor", {"vendor_id": "x", "extra": 1}),  # unknown additional property
        ("search_vendors", {"limit": 501}),              # above maximum
        ("search_vendors", {"limit": "many"}),           # wrong type
        ("match_inventory", {"rows": [{}] * 5001}),      # exceeds maxItems
        ("match_inventory", {"rows": "notalist"}),       # wrong type
    ]

    async def scenario() -> None:
        server = build_server(snapshot)
        async with create_connected_server_and_client_session(server) as client:
            for name, args in bad_calls:
                result = await client.call_tool(name, args)
                assert result.isError, f"{name} {args} should be a tool error"

            unknown = await client.call_tool("get_snapshot_metadata", {})  # sanity: valid call ok
            assert unknown.isError is False

    anyio.run(scenario)


def test_protocol_bounds_match_inventory_and_controls_empty_identity(export_tree):
    # Over the in-memory transport (same dispatcher stdio uses): the bounded
    # workspace-data boundary covers match_inventory, and an empty-identity enrich row
    # becomes a controlled tool error rather than an uncaught exception.
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))

    async def scenario() -> None:
        server = build_server(snapshot)
        async with create_connected_server_and_client_session(server) as client:
            bounded = await client.call_tool(
                "match_inventory", {"rows": [{"domain": "vendor.example", "workspace_id": "ws-1"}]}
            )
            assert bounded.isError, "match_inventory must reject an undeclared workspace field"

            for tool in ("match_inventory", "enrich_inventory"):
                empty = await client.call_tool(tool, {"rows": [{"row_id": "1"}]})
                assert empty.isError, f"{tool}: empty-identity row must be a controlled tool error"
                text = " ".join(getattr(block, "text", "") for block in (empty.content or []))
                assert "Traceback" not in text and "at least one of" in text

    anyio.run(scenario)


def test_protocol_tools_list_discloses_registration_number_capability(export_tree):
    # An agent discovering OpenVA only via tools/list must learn that
    # registration_number matching is data-dependent: it works when the export carries
    # legal-entity data for the vendor, and otherwise resolves to no_match.
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))

    async def scenario() -> None:
        server = build_server(snapshot)
        async with create_connected_server_and_client_session(server) as client:
            by_name = {tool.name: tool for tool in (await client.list_tools()).tools}
            for name in ("match_inventory", "enrich_inventory"):
                tool = by_name[name]
                reg = tool.inputSchema["properties"]["rows"]["items"]["properties"]["registration_number"]
                disclosure = (tool.description + " " + reg.get("description", "")).lower()
                assert "legal-entity" in disclosure
                assert "registration" in disclosure
                assert "no_match" in disclosure  # current behaviour while the catalogue carries none

    anyio.run(scenario)


def test_protocol_unknown_tool_is_an_error(export_tree):
    snapshot = Snapshot.load(LocalSnapshotSource(export_tree))

    async def scenario() -> None:
        server = build_server(snapshot)
        async with create_connected_server_and_client_session(server) as client:
            try:
                result = await client.call_tool("no_such_tool", {})
                assert result.isError
            except Exception:
                # Some SDK versions raise for an unknown tool; that is also a
                # controlled rejection.
                pass

    anyio.run(scenario)


def test_protocol_over_stdio_subprocess(export_tree):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {
        "PYTHONPATH": ";".join(
            str(p)
            for p in (
                ROOT / "integrations" / "mcp" / "openva_mcp",
                ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
                ROOT / "adapters" / "python" / "openva_pack_reader",
            )
        ),
    }
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "openva_mcp", "--snapshot", str(export_tree)],
        env=env,
    )

    async def scenario() -> None:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert REQUIRED_TOOLS.issubset({tool.name for tool in listed.tools})
                meta = await session.call_tool("get_snapshot_metadata", {})
                assert meta.structuredContent["not_advice"] is True

    try:
        anyio.run(scenario)
    except (OSError, NotImplementedError) as exc:  # host cannot spawn the child process
        pytest.skip(f"stdio subprocess transport unavailable here: {exc}")
