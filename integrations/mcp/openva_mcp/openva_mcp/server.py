"""MCP server wiring and CLI.

The tool registry (``TOOL_SPECS``) is declared independently of the MCP SDK so
the tool surface can be tested without it. ``build_server`` registers each spec
on a low-level ``mcp.server.Server`` so the exact ``input_schema`` declared here
is what a real ``tools/list`` request publishes, and each handler returns a
plain dict that the SDK surfaces as ``structuredContent``.

``main`` resolves the data mode (pinned local directory or hosted base URL),
loads and integrity-checks the snapshot once at startup, and serves over stdio.
The server is read-only by construction of its tool surface: it exposes only the
functions in ``TOOL_SPECS`` and never accepts a GitHub token or any write path.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Callable

from openva_mcp import tools
from openva_mcp.snapshot import (
    LocalSnapshotSource,
    RemoteSnapshotSource,
    Snapshot,
)

_STRING = {"type": "string"}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[[Snapshot, dict[str, Any]], dict[str, Any]]


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "search_vendors",
        "Search catalogued vendors by id, canonical name, or official domain.",
        _obj({"query": {"type": ["string", "null"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
        lambda snapshot, args: tools.search_vendors(snapshot, args.get("query"), int(args.get("limit", 50))),
    ),
    ToolSpec(
        "get_vendor",
        "Get a vendor's export (identity, domains, catalog status, and sources).",
        _obj({"vendor_id": _STRING}, ["vendor_id"]),
        lambda snapshot, args: tools.get_vendor(snapshot, args["vendor_id"]),
    ),
    ToolSpec(
        "list_vendor_sources",
        "List a vendor's public assurance sources with original URLs and observed health.",
        _obj({"vendor_id": _STRING}, ["vendor_id"]),
        lambda snapshot, args: tools.list_vendor_sources(snapshot, args["vendor_id"]),
    ),
    ToolSpec(
        "get_source",
        "Get a single source record by source_id.",
        _obj({"source_id": _STRING}, ["source_id"]),
        lambda snapshot, args: tools.get_source(snapshot, args["source_id"]),
    ),
    ToolSpec(
        "get_source_health",
        "Get the latest observed health and observation timestamp for a source.",
        _obj({"source_id": _STRING}, ["source_id"]),
        lambda snapshot, args: tools.get_source_health(snapshot, args["source_id"]),
    ),
    ToolSpec(
        "get_vendor_changes",
        "Get the latest recorded change events for a vendor's sources.",
        _obj({"vendor_id": _STRING}, ["vendor_id"]),
        lambda snapshot, args: tools.get_vendor_changes(snapshot, args["vendor_id"]),
    ),
    ToolSpec(
        "match_inventory",
        "Match inventory rows (domain / vendor_name / business_entity_name / registration_number) "
        "to vendors. Each row's match_status is matched, ambiguous, or no_match.",
        _obj(
            {"rows": {"type": "array", "items": {"type": "object"}, "maxItems": 5000}},
            ["rows"],
        ),
        lambda snapshot, args: tools.match_inventory(snapshot, list(args["rows"])),
    ),
    ToolSpec(
        "get_snapshot_metadata",
        "Get snapshot identity (commit, digest, generated_at, mode) and catalog counts.",
        _obj({}),
        lambda snapshot, args: tools.get_snapshot_metadata(snapshot),
    ),
    ToolSpec(
        "verify_snapshot",
        "Recompute and cross-check the content digest and schema of every export in the snapshot.",
        _obj({}),
        lambda snapshot, args: tools.verify_snapshot(snapshot),
    ),
]

SPEC_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}


def resolve_snapshot(args: argparse.Namespace) -> Snapshot:
    if args.snapshot:
        return Snapshot.load(LocalSnapshotSource(args.snapshot))
    if args.base_url:
        return Snapshot.load(RemoteSnapshotSource(args.base_url, cache_dir=args.cache_dir))
    raise SystemExit("provide --snapshot <dir> or --base-url <url>")


def _tool_error(message: str):
    from mcp import types

    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], isError=True)


def build_server(snapshot: Snapshot):
    """Build a low-level MCP server exposing the read-only tools (SDK imported lazily)."""
    import jsonschema
    from mcp import types
    from mcp.server.lowlevel import Server

    server: Server = Server("openva")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(name=spec.name, description=spec.description, inputSchema=spec.input_schema)
            for spec in TOOL_SPECS
        ]

    # validate_input=False: this handler is the single authoritative validation
    # point. Every request is checked against the tool's declared input_schema
    # before dispatch, and invalid input becomes a controlled tool error rather
    # than an uncaught exception or a silently accepted bad argument.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]):
        spec = SPEC_BY_NAME.get(name)
        if spec is None:
            return _tool_error(f"unknown tool: {name}")
        try:
            jsonschema.validate(arguments or {}, spec.input_schema)
        except jsonschema.ValidationError as exc:
            return _tool_error(f"invalid input for {name}: {exc.message}")
        # Returning a dict surfaces as structuredContent (and JSON text content).
        return spec.func(snapshot, arguments or {})

    return server


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openva-mcp", description="Read-only OpenVA MCP server.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--snapshot", help="Path to a local OpenVA export tree or extracted agent-export release bundle.")
    source.add_argument("--base-url", help="Base URL of a hosted OpenVA export tree.")
    parser.add_argument("--cache-dir", default=None, help="Optional cache dir for disclosed remote fallback.")
    parser.add_argument("--verify", action="store_true", help="Verify the snapshot and exit.")
    return parser


def run_stdio(server) -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(_run)


def main(argv: list[str] | None = None) -> int:
    from openva_mcp.snapshot import SnapshotError

    args = build_arg_parser().parse_args(argv)
    try:
        # Snapshot load enforces digest integrity and supported schema.
        snapshot = resolve_snapshot(args)
        if args.verify:
            report = tools.verify_snapshot(snapshot)["verification"]
            print("ok" if report["ok"] else "FAILED", snapshot.commit_sha, file=sys.stderr)
            return 0 if report["ok"] else 1
    except SnapshotError as exc:
        print(f"snapshot error: {exc}", file=sys.stderr)
        return 1
    run_stdio(build_server(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
