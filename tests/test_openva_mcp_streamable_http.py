"""Streamable HTTP transport tests, driven through the real ASGI application.

These exercise the same ``TOOL_SPECS`` registry and ``build_server`` wiring that
stdio uses, so there is no transport-specific tool drift. They cover the JSON-RPC
lifecycle (initialize / tools/list / tools/call), controlled error handling,
Origin validation, request-size bounds, liveness/readiness probes (including
fail-closed on snapshot integrity), and the public-binding guard.
"""

import argparse
import json
import sys
from pathlib import Path

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
pytest.importorskip("starlette")

from starlette.testclient import TestClient  # noqa: E402

from openva_mcp.server import (  # noqa: E402
    TOOL_SPECS,
    TransportConfig,
    build_streamable_http_app,
    check_public_binding,
    default_allowed_hosts,
    transport_config_from_args,
)
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
    "enrich_inventory",
    "get_snapshot_metadata",
    "verify_snapshot",
}

RPC_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _export_tree(tmp_path: Path) -> Path:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    return build(tmp_path, latest_observations=run_artifact())


@pytest.fixture
def snapshot(tmp_path) -> Snapshot:
    return Snapshot.load(LocalSnapshotSource(_export_tree(tmp_path)))


def _config(**overrides) -> TransportConfig:
    base = dict(transport="streamable-http", allowed_hosts=("testserver",))
    base.update(overrides)
    return TransportConfig(**base)


def _rpc(client, method, params=None, *, _id=1, headers=None):
    body = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers={**RPC_HEADERS, **(headers or {})}, json=body)


# --------------------------------------------------------------------------- protocol


def test_initialize_list_and_call(snapshot):
    with TestClient(build_streamable_http_app(snapshot, _config(allowed_origins=("https://agent.example",)))) as client:
        init = _rpc(
            client,
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
        )
        assert init.status_code == 200
        assert init.json()["result"]["serverInfo"]["name"] == "openva"

        listed = _rpc(client, "tools/list", _id=2).json()["result"]["tools"]
        assert REQUIRED_TOOLS.issubset({tool["name"] for tool in listed})

        called = _rpc(
            client,
            "tools/call",
            {"name": "enrich_inventory", "arguments": {"rows": [{"row_id": "1", "domain": "vendor.example"}], "source_types": ["dpa"]}},
            _id=3,
        ).json()["result"]
        assert called["isError"] is False
        structured = called["structuredContent"]
        assert structured["not_advice"] is True
        assert structured["results"][0]["match"]["vendor_id"] == "example-vendor"
        assert structured["snapshot"]["commit_sha"] == snapshot.commit_sha


def test_transport_parity_with_tool_specs(snapshot):
    expected = {spec.name: (spec.description, spec.input_schema) for spec in TOOL_SPECS}
    with TestClient(build_streamable_http_app(snapshot, _config())) as client:
        listed = _rpc(client, "tools/list").json()["result"]["tools"]
    published = {tool["name"]: (tool["description"], tool["inputSchema"]) for tool in listed}
    assert published == expected


def test_invalid_tool_and_arguments_are_tool_errors(snapshot):
    with TestClient(build_streamable_http_app(snapshot, _config())) as client:
        unknown = _rpc(client, "tools/call", {"name": "no_such_tool", "arguments": {}}, _id=2)
        assert unknown.json()["result"]["isError"] is True
        bad_args = _rpc(client, "tools/call", {"name": "get_vendor", "arguments": {}}, _id=3)
        assert bad_args.json()["result"]["isError"] is True
        over_limit = _rpc(
            client,
            "tools/call",
            {"name": "enrich_inventory", "arguments": {"rows": [{"vendor_name": "x"}] * 501}},
            _id=4,
        )
        assert over_limit.json()["result"]["isError"] is True


def test_malformed_jsonrpc_is_rejected(snapshot):
    with TestClient(build_streamable_http_app(snapshot, _config())) as client:
        resp = client.post("/mcp", headers=RPC_HEADERS, content=b"{ not json")
    assert resp.status_code == 400


# --------------------------------------------------------------------------- origin validation


def test_origin_allowed_denied_and_absent(snapshot):
    with TestClient(build_streamable_http_app(snapshot, _config(allowed_origins=("https://agent.example",)))) as client:
        allowed = _rpc(client, "tools/list", _id=1, headers={"Origin": "https://agent.example"})
        assert allowed.status_code == 200
        denied = _rpc(client, "tools/list", _id=2, headers={"Origin": "https://evil.example"})
        assert denied.status_code == 403
        absent = _rpc(client, "tools/list", _id=3)  # no Origin: allowed for non-browser clients
        assert absent.status_code == 200


def test_empty_origin_allow_list_is_not_a_wildcard(snapshot):
    # No configured origins: a present browser Origin is rejected, never wildcarded.
    with TestClient(build_streamable_http_app(snapshot, _config(allowed_origins=()))) as client:
        denied = _rpc(client, "tools/list", headers={"Origin": "https://anything.example"})
    assert denied.status_code == 403


# --------------------------------------------------------------------------- request-size bound


def test_oversized_body_is_rejected_413(snapshot):
    with TestClient(build_streamable_http_app(snapshot, _config(max_request_bytes=400))) as client:
        big = {"name": "enrich_inventory", "arguments": {"rows": [{"vendor_name": "Z" * 5000}]}}
        resp = _rpc(client, "tools/call", big)
    assert resp.status_code == 413


# --------------------------------------------------------------------------- probes


def test_healthz_and_readyz_when_loaded(snapshot):
    with TestClient(build_streamable_http_app(snapshot, _config())) as client:
        assert client.get("/healthz").status_code == 200
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"


def test_readyz_fails_when_snapshot_unavailable():
    # Snapshot load failed upstream -> None passed in -> never ready, /mcp fails closed.
    with TestClient(build_streamable_http_app(None, _config())) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 503
        mcp = _rpc(client, "tools/list")
        assert mcp.status_code == 503


def test_readyz_fails_closed_on_integrity_failure(tmp_path):
    tree = _export_tree(tmp_path)
    snapshot = Snapshot.load(LocalSnapshotSource(tree))
    # Tamper a child export after load; startup verification must fail closed.
    target = tree / "vendors" / "example-vendor.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["domains"] = ["tampered.example"]
    target.write_text(json.dumps(doc), encoding="utf-8")
    with TestClient(build_streamable_http_app(snapshot, _config())) as client:
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json()["detail"] == "integrity_failed"
        assert _rpc(client, "tools/list").status_code == 503


# --------------------------------------------------------------------------- public-binding guard / config


def test_public_binding_guard_refuses_non_loopback_without_optin():
    with pytest.raises(SystemExit):
        check_public_binding(TransportConfig(transport="streamable-http", host="0.0.0.0", public_read_enabled=False))
    with pytest.raises(SystemExit):
        check_public_binding(TransportConfig(transport="streamable-http", host="10.0.0.5", public_read_enabled=False))
    # Opt-in or loopback is permitted; stdio is never guarded.
    check_public_binding(TransportConfig(transport="streamable-http", host="0.0.0.0", public_read_enabled=True))
    check_public_binding(TransportConfig(transport="streamable-http", host="127.0.0.1"))
    check_public_binding(TransportConfig(transport="stdio", host="0.0.0.0"))


def test_default_transport_config_is_loopback_stdio():
    args = argparse.Namespace(
        transport=None, host=None, port=None, mount_path=None,
        public_read=False, allowed_origins=None, allowed_hosts=None,
    )
    config = transport_config_from_args(args)
    assert config.transport == "stdio"
    assert config.host == "127.0.0.1"
    assert config.port == 8000
    assert config.mount_path == "/mcp"
    assert config.public_read_enabled is False
    assert config.allowed_origins == ()
    # Host allow-list defaults to loopback names (never empty, never a public host).
    assert "127.0.0.1:8000" in config.allowed_hosts
    assert default_allowed_hosts("0.0.0.0", 8000) == ()


# --------------------------------------------------------------------------- logging


def test_successful_request_does_not_log_request_body(snapshot, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        with TestClient(build_streamable_http_app(snapshot, _config())) as client:
            _rpc(
                client,
                "tools/call",
                {"name": "enrich_inventory", "arguments": {"rows": [{"row_id": "1", "domain": "secret-vendor.example"}]}},
            )
    # The vendor identity in the request body must not appear in logs.
    assert "secret-vendor.example" not in caplog.text
