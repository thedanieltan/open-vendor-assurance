"""MCP server wiring and CLI.

The tool registry (``TOOL_SPECS``) is declared independently of the MCP SDK so
the tool surface can be tested without it. ``build_server`` imports the SDK
lazily and registers each spec; ``main`` resolves the data mode (pinned local
directory or hosted base URL), loads and integrity-checks the snapshot once at
startup, and serves over stdio.

The server is read-only by construction: it exposes only the functions in
``TOOL_SPECS`` and never accepts a GitHub token or any write path.
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
    func: Callable[..., dict[str, Any]]


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
        "Match inventory rows (domain / vendor_name / business_entity_name) to vendors; "
        "ambiguous and unmatched rows stay explicitly so.",
        _obj(
            {
                "rows": {
                    "type": "array",
                    "items": {"type": "object"},
                    "maxItems": 5000,
                }
            },
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
        "Recompute and cross-check the content digest of every export in the snapshot.",
        _obj({}),
        lambda snapshot, args: tools.verify_snapshot(snapshot),
    ),
]


def resolve_snapshot(args: argparse.Namespace) -> Snapshot:
    if args.snapshot:
        return Snapshot.load(LocalSnapshotSource(args.snapshot))
    if args.base_url:
        source = RemoteSnapshotSource(args.base_url, cache_dir=args.cache_dir)
        return Snapshot.load(source)
    raise SystemExit("provide --snapshot <dir> or --base-url <url>")


def build_server(snapshot: Snapshot):
    """Build a FastMCP server exposing the read-only tools (SDK imported lazily)."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("openva")
    for spec in TOOL_SPECS:
        def make_handler(spec: ToolSpec):
            async def handler(**arguments: Any) -> dict[str, Any]:
                return spec.func(snapshot, arguments)

            handler.__name__ = spec.name
            handler.__doc__ = spec.description
            return handler

        server.add_tool(
            make_handler(spec),
            name=spec.name,
            description=spec.description,
        )
    return server


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openva-mcp", description="Read-only OpenVA MCP server.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--snapshot", help="Path to a local OpenVA export or release directory.")
    source.add_argument("--base-url", help="Base URL of a hosted OpenVA export tree.")
    parser.add_argument("--cache-dir", default=None, help="Optional cache dir for disclosed remote fallback.")
    parser.add_argument("--verify", action="store_true", help="Verify the snapshot and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    snapshot = resolve_snapshot(args)
    if args.verify:
        report = tools.verify_snapshot(snapshot)["verification"]
        print("ok" if report["ok"] else "FAILED", snapshot.commit_sha, file=sys.stderr)
        return 0 if report["ok"] else 1
    build_server(snapshot).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
