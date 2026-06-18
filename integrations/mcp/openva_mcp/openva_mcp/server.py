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
import os
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

# Bounded enrichment row: only the four vendor-identity fields plus an opaque
# row_id. additionalProperties=False keeps unrelated workspace columns out, and
# the per-field maxLength bounds caller-supplied strings before any processing.
_ENRICH_MAX_FIELD_LEN = 512
_ENRICH_MAX_ROWS = 500
_ENRICH_MAX_SOURCE_TYPES = 64
_ENRICH_ROW_SCHEMA = {
    "type": "object",
    "properties": {
        "row_id": {"type": ["string", "integer", "null"], "maxLength": 128},
        "vendor_name": {"type": ["string", "null"], "maxLength": _ENRICH_MAX_FIELD_LEN},
        "domain": {"type": ["string", "null"], "maxLength": _ENRICH_MAX_FIELD_LEN},
        "business_entity_name": {"type": ["string", "null"], "maxLength": _ENRICH_MAX_FIELD_LEN},
        "registration_number": {"type": ["string", "null"], "maxLength": _ENRICH_MAX_FIELD_LEN},
    },
    "additionalProperties": False,
}


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
        "enrich_inventory",
        "Match a bounded batch of vendor-identity rows (row_id / vendor_name / domain / "
        "business_entity_name / registration_number) and attach their public assurance "
        "sources, optionally filtered by source_type. For agents that have already read a "
        "workspace through their own connector: send only vendor-identity fields, never "
        "workspace content. Input order and duplicates are preserved, row_id is echoed, "
        "ambiguous stays ambiguous, no_match stays no-match. Read-only; not advice.",
        _obj(
            {
                "rows": {
                    "type": "array",
                    "items": _ENRICH_ROW_SCHEMA,
                    "minItems": 1,
                    "maxItems": _ENRICH_MAX_ROWS,
                },
                "source_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string", "maxLength": 128},
                    "maxItems": _ENRICH_MAX_SOURCE_TYPES,
                },
            },
            ["rows"],
        ),
        lambda snapshot, args: tools.enrich_inventory(
            snapshot, list(args["rows"]), args.get("source_types")
        ),
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


# Hosts that are not a remote/public bind. A non-loopback bind is refused unless
# the operator explicitly opts in (OPENVA_MCP_PUBLIC_READ_ENABLED), so the default
# posture stays local even with the streamable-http transport selected.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "0.0.0.0", "localhost"})
PUBLIC_BIND_HOSTS = frozenset({"0.0.0.0", "::"})
_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})
TRANSPORT_STDIO = "stdio"
TRANSPORT_STREAMABLE_HTTP = "streamable-http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_MOUNT_PATH = "/mcp"


@dataclass(frozen=True)
class TransportConfig:
    """Resolved transport settings. stdio is the default and is unaffected by the
    streamable-http fields, so existing stdio invocations keep working unchanged."""

    transport: str = TRANSPORT_STDIO
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    mount_path: str = DEFAULT_MOUNT_PATH
    # Read-only public bind opt-in. Never enables any write, candidate-intake,
    # GitHub-write, live-verification, arbitrary-fetch, or workspace capability —
    # there are none in the tool surface. It only permits a non-loopback bind of
    # the existing read-only tools.
    public_read_enabled: bool = False
    allowed_origins: tuple[str, ...] = ()
    allowed_hosts: tuple[str, ...] = ()
    access_log: bool = False
    # Bound the JSON-RPC body before the transport parses it. Generous for a
    # bounded enrich batch; rejects a single oversized payload up front.
    max_request_bytes: int = 1_000_000


def _parse_origins(raw: str) -> tuple[str, ...]:
    """Comma-separated origins; whitespace stripped, blanks dropped, order-preserving
    de-dup. An absent or empty value yields an empty tuple, never a wildcard."""
    seen: list[str] = []
    for entry in (raw or "").split(","):
        value = entry.strip()
        if value and value not in seen:
            seen.append(value)
    return tuple(seen)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return raw in _TRUE_TOKENS if raw else default


def default_allowed_hosts(host: str, port: int) -> tuple[str, ...]:
    """Default Host allow-list when the operator does not supply one.

    DNS-rebinding protection is always on for the HTTP transport, and the SDK
    rejects every request when the Host allow-list is empty, so a usable default is
    derived from the configured bind. For a loopback bind this covers the loopback
    names with and without the port; a public bind requires an explicit
    OPENVA_MCP_ALLOWED_HOSTS (so a real deployment names its own host)."""
    if host in PUBLIC_BIND_HOSTS:
        return ()
    names = {host, f"{host}:{port}"}
    if host in ("127.0.0.1", "localhost"):
        names |= {"127.0.0.1", "localhost", f"127.0.0.1:{port}", f"localhost:{port}"}
    return tuple(sorted(names))


def transport_config_from_args(args: argparse.Namespace) -> TransportConfig:
    """Resolve transport config from CLI args, falling back to OPENVA_MCP_* env vars.

    Defaults keep stdio behaviour; env equivalents exist for container deployment."""
    transport = (args.transport or os.environ.get("OPENVA_MCP_TRANSPORT") or TRANSPORT_STDIO).strip()
    host = (args.host or os.environ.get("OPENVA_MCP_HOST") or DEFAULT_HOST).strip()
    port_raw = args.port or os.environ.get("OPENVA_MCP_PORT") or DEFAULT_PORT
    mount_path = (args.mount_path or os.environ.get("OPENVA_MCP_MOUNT_PATH") or DEFAULT_MOUNT_PATH).strip()
    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"invalid port: {port_raw!r}") from exc
    if not mount_path.startswith("/"):
        mount_path = "/" + mount_path
    public_read = bool(args.public_read) or _env_bool("OPENVA_MCP_PUBLIC_READ_ENABLED")
    origins = _parse_origins(args.allowed_origins or os.environ.get("OPENVA_MCP_ALLOWED_ORIGINS", ""))
    hosts = _parse_origins(args.allowed_hosts or os.environ.get("OPENVA_MCP_ALLOWED_HOSTS", ""))
    if not hosts:
        hosts = default_allowed_hosts(host, port)
    access_log = _env_bool("OPENVA_MCP_ACCESS_LOG_ENABLED")
    return TransportConfig(
        transport=transport,
        host=host,
        port=port,
        mount_path=mount_path,
        public_read_enabled=public_read,
        allowed_origins=origins,
        allowed_hosts=hosts,
        access_log=access_log,
    )


def check_public_binding(config: TransportConfig) -> None:
    """Fail closed on a non-loopback bind unless public-read is explicitly enabled."""
    if config.transport != TRANSPORT_STREAMABLE_HTTP:
        return
    if config.host not in LOOPBACK_HOSTS and not config.public_read_enabled:
        raise SystemExit(
            f"refusing to bind {config.host!r}: set OPENVA_MCP_PUBLIC_READ_ENABLED=true "
            "(or --public-read) to expose the read-only tools on a non-loopback address"
        )
    if config.host in PUBLIC_BIND_HOSTS and not config.public_read_enabled:
        raise SystemExit(
            f"refusing to bind {config.host!r}: set OPENVA_MCP_PUBLIC_READ_ENABLED=true "
            "(or --public-read) to expose the read-only tools publicly"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openva-mcp", description="Read-only OpenVA MCP server.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--snapshot", help="Path to a local OpenVA export tree or extracted agent-export release bundle.")
    source.add_argument("--base-url", help="Base URL of a hosted OpenVA export tree.")
    parser.add_argument("--cache-dir", default=None, help="Optional cache dir for disclosed remote fallback.")
    parser.add_argument("--verify", action="store_true", help="Verify the snapshot and exit.")
    parser.add_argument(
        "--transport",
        choices=[TRANSPORT_STDIO, TRANSPORT_STREAMABLE_HTTP],
        default=None,
        help="Transport (default: stdio; env OPENVA_MCP_TRANSPORT).",
    )
    parser.add_argument("--host", default=None, help="Streamable HTTP bind host (default: 127.0.0.1).")
    parser.add_argument("--port", default=None, type=int, help="Streamable HTTP bind port (default: 8000).")
    parser.add_argument("--mount-path", default=None, help="Streamable HTTP MCP mount path (default: /mcp).")
    parser.add_argument(
        "--public-read",
        action="store_true",
        help="Allow a non-loopback streamable-http bind of the read-only tools (env OPENVA_MCP_PUBLIC_READ_ENABLED).",
    )
    parser.add_argument("--allowed-origins", default=None, help="Comma-separated Origin allow-list (env OPENVA_MCP_ALLOWED_ORIGINS).")
    parser.add_argument("--allowed-hosts", default=None, help="Comma-separated Host allow-list (env OPENVA_MCP_ALLOWED_HOSTS).")
    return parser


def run_stdio(server) -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    anyio.run(_run)


class _BodyLimit:
    """ASGI guard that bounds a request body before the MCP transport parses it.

    A declared Content-Length over the cap is rejected up front; a chunked body is
    buffered up to the cap (never holding more than ~max_bytes) and replayed, so a
    single oversized JSON-RPC payload cannot exhaust memory regardless of framing."""

    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    if int(value) > self.max_bytes:
                        await self._reject(scope, send)
                        return
                except ValueError:
                    pass
                break

        buffered: list[dict[str, Any]] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                if message["type"] == "http.disconnect":
                    break
                continue
            total += len(message.get("body", b"") or b"")
            if total > self.max_bytes:
                await self._reject(scope, send)
                return
            buffered.append(message)
            more = message.get("more_body", False)

        replayed_terminal = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed_terminal
            if buffered:
                return buffered.pop(0)
            if not replayed_terminal:
                replayed_terminal = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, scope, send) -> None:
        from starlette.responses import JSONResponse

        async def _empty_receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        await JSONResponse(
            {"error": "payload_too_large", "message": f"request body exceeds the maximum of {self.max_bytes} bytes"},
            status_code=413,
        )(scope, _empty_receive, send)


def build_streamable_http_app(snapshot: Snapshot | None, config: TransportConfig):
    """Build the Starlette ASGI app exposing the read-only MCP tools over Streamable HTTP.

    The same ``TOOL_SPECS`` registry and ``build_server`` wiring back this transport
    and stdio, so there is no tool drift between them. DNS-rebinding protection is
    always on (Host + Origin validation via the SDK's transport security). Readiness
    fails closed: snapshot integrity is verified at startup, and ``/mcp`` returns 503
    until verification has passed. ``snapshot`` may be ``None`` when loading failed —
    then the server is never built and readiness stays not-ready."""
    import contextlib

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Mount, Route

    state = {"ready": False, "detail": "starting"}
    server = build_server(snapshot) if snapshot is not None else None

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(config.allowed_hosts),
        allowed_origins=list(config.allowed_origins),
    )
    session_manager = (
        StreamableHTTPSessionManager(
            app=server,
            event_store=None,
            json_response=True,
            stateless=True,
            security_settings=security,
        )
        if server is not None
        else None
    )

    async def healthz(_request) -> JSONResponse:
        # Liveness: the process is up. No snapshot dependency.
        return JSONResponse({"status": "ok"})

    async def readyz(_request) -> JSONResponse:
        ok = state["ready"]
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "detail": state["detail"]},
            status_code=200 if ok else 503,
        )

    async def handle_mcp(scope, receive, send) -> None:
        # Fail closed: never serve tools until the snapshot has verified.
        if session_manager is None or not state["ready"]:
            await Response("snapshot not ready", status_code=503)(scope, receive, send)
            return
        await session_manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        if snapshot is not None:
            try:
                report = snapshot.verify()
                state["ready"] = bool(report.get("ok"))
                state["detail"] = "ok" if state["ready"] else "integrity_failed"
            except Exception:  # integrity / load failure -> fail closed, no detail leak
                state["ready"] = False
                state["detail"] = "integrity_failed"
        else:
            state["detail"] = "snapshot_unavailable"
        if session_manager is not None:
            async with session_manager.run():
                yield
        else:
            yield

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Mount(config.mount_path, app=_BodyLimit(handle_mcp, max_bytes=config.max_request_bytes)),
        ],
        lifespan=lifespan,
    )


def serve_streamable_http(snapshot: Snapshot, config: TransportConfig) -> None:
    import uvicorn

    app = build_streamable_http_app(snapshot, config)
    # access_log defaults False so request lines (and any query) are never logged;
    # the MCP path carries no vendor identity, and bodies are never logged.
    uvicorn.run(app, host=config.host, port=config.port, access_log=config.access_log, log_level="warning")


def main(argv: list[str] | None = None) -> int:
    from openva_mcp.snapshot import SnapshotError

    args = build_arg_parser().parse_args(argv)
    transport_config = transport_config_from_args(args)
    # Guard the public bind before loading anything, so a misconfigured non-loopback
    # bind fails fast and never starts serving.
    check_public_binding(transport_config)
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
    if transport_config.transport == TRANSPORT_STREAMABLE_HTTP:
        serve_streamable_http(snapshot, transport_config)
    else:
        run_stdio(build_server(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
