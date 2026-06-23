"""Tests for the WP-02I live ``resolve_*`` MCP tool over the hosted transport.

The live tool resolves vendors by submitting bounded vendor IDENTITIES to the
hosted ``/v1`` verify transport (create + poll) — it never fetches a caller-supplied
URL. It is registered ONLY when an operator explicitly configures a hosted endpoint
(off by default); with none configured the static MCP surface is unchanged. These
tests inject a deterministic FAKE hosted-transport client/responses (NO real
network) and pin: resolution over the hosted transport when configured; read-only +
bounded (over-cap rejected/clamped); no arbitrary-URL tool (threat-model lock);
non-advisory boundary; rollback to the static-canonical surface when unconfigured;
and that the job_token / Authorization is never logged or echoed.
"""

import json
import sys
from pathlib import Path

import anyio
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
from openva_mcp.hosted_transport import (  # noqa: E402
    HostedResponse,
    HostedTransportClient,
    HostedTransportError,
)
from openva_mcp.server import (  # noqa: E402
    LIVE_RESOLVE_TOOL_NAME,
    TOOL_SPECS,
    active_tool_specs,
    build_hosted_client_from_env,
    build_live_resolve_spec,
    build_server,
    hosted_endpoint_from_env,
)
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot  # noqa: E402

from tests.test_agent_export import build, make_repo, run_artifact, write_ledger_event  # noqa: E402


# --------------------------------------------------------------------------- fakes


class _FakeTransport:
    """A deterministic, no-network transport recording every call.

    Mirrors the real (method, url, json_body, bearer_token) -> HostedResponse
    contract. Drives a two-step create+poll: the create returns a job handle, the
    first poll returns ``completed`` with a canned, non-advisory result."""

    def __init__(self, *, result=None, poll_state="completed", create_status=201):
        self.calls = []  # (method, url, json_body, bearer_token)
        self._result = result if result is not None else {"resolved": []}
        self._poll_state = poll_state
        self._create_status = create_status

    def __call__(self, method, url, json_body, bearer_token):
        self.calls.append((method, url, json_body, bearer_token))
        if method == "POST":
            return HostedResponse(
                status=self._create_status,
                body={"job_id": "11111111-2222-3333-4444-555555555555", "job_token": "secret-cap-token", "state": "received"},
            )
        # GET poll
        return HostedResponse(
            status=200,
            body={
                "job_id": "11111111-2222-3333-4444-555555555555",
                "state": self._poll_state,
                "row_count": 1,
                "result": self._result,
                "error_code": None,
                "not_advice": True,
            },
        )


class _RecordingClient:
    """A fake HostedTransportClient with the same ``resolve`` surface the tool calls."""

    def __init__(self, resolution=None, raises=None):
        self.calls = []
        self._resolution = resolution if resolution is not None else {"state": "completed", "result": {"resolved": []}, "not_advice": True}
        self._raises = raises

    def resolve(self, rows, source_types=None):
        self.calls.append((rows, source_types))
        if self._raises is not None:
            raise self._raises
        return self._resolution


@pytest.fixture
def snapshot(tmp_path) -> Snapshot:
    make_repo(tmp_path)
    write_ledger_event(tmp_path, observed_at="2026-06-01T05:30:00Z")
    return Snapshot.load(LocalSnapshotSource(build(tmp_path, latest_observations=run_artifact())))


# --------------------------------------------------------------------------- resolves over hosted transport


def test_resolve_over_hosted_transport_when_configured(snapshot):
    client = _RecordingClient(
        resolution={"state": "completed", "result": {"resolved": [{"row_id": "1", "match": {"status": "matched"}}]}, "not_advice": True}
    )
    out = tools.resolve_vendor_sources(snapshot, client, [{"row_id": "1", "domain": "vendor.example"}], ["dpa"])
    # The tool forwarded only the bounded identity row + row_id to the hosted transport.
    assert client.calls == [([{"row_id": "1", "domain": "vendor.example"}], ["dpa"])]
    # The hosted resolution is surfaced under the OpenVA snapshot envelope.
    assert out["resolution"]["result"]["resolved"][0]["match"]["status"] == "matched"
    assert out["count"] == 1
    assert out["snapshot"]["commit_sha"] == snapshot.commit_sha


def test_resolve_forwards_only_identity_fields(snapshot):
    # Even if (hypothetically) an extra key reached the func, only row_id + the four
    # identity fields are forwarded to the transport — nothing else leaks downstream.
    client = _RecordingClient()
    tools.resolve_vendor_sources(
        snapshot,
        client,
        [{"row_id": "7", "vendor_name": "Stripe", "domain": "stripe.com", "business_entity_name": None, "registration_number": None}],
        None,
    )
    forwarded_rows, source_types = client.calls[0]
    assert source_types is None
    # None-valued identity fields are dropped; row_id + present identities forwarded.
    assert forwarded_rows == [{"row_id": "7", "vendor_name": "Stripe", "domain": "stripe.com"}]
    assert all(set(r).issubset({"row_id", "vendor_name", "domain", "business_entity_name", "registration_number"}) for r in forwarded_rows)


def test_empty_identity_row_is_rejected_before_transport(snapshot):
    client = _RecordingClient()
    with pytest.raises(ValueError):
        tools.resolve_vendor_sources(snapshot, client, [{"row_id": "1"}], None)
    # Nothing was ever sent to the hosted transport.
    assert client.calls == []


def test_transport_failure_becomes_controlled_value_error(snapshot):
    client = _RecordingClient(raises=HostedTransportError("hosted verify transport is disabled"))
    with pytest.raises(ValueError) as excinfo:
        tools.resolve_vendor_sources(snapshot, client, [{"domain": "vendor.example"}], None)
    # Generic message, no token / identity leakage.
    assert "hosted resolve unavailable" in str(excinfo.value)


# --------------------------------------------------------------------------- bounded


def test_live_tool_schema_bounds_rows_and_source_types():
    client = _RecordingClient()
    spec = build_live_resolve_spec(client)
    schema = spec.input_schema
    # Within bounds passes.
    jsonschema.validate({"rows": [{"row_id": "1", "vendor_name": "Stripe"}]}, schema)
    # Over the hosted verify row cap (20) is rejected by the declared schema.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x"}] * 21}, schema)
    # Over the hosted verify source-type cap (4) is rejected.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x"}], "source_types": ["a", "b", "c", "d", "e"]}, schema)
    # Over-long identity field is rejected.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "z" * 513}]}, schema)
    # An undeclared workspace column is rejected (no workspace data leaks in).
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x", "workspace_id": "abc"}]}, schema)


# --------------------------------------------------------------------------- no arbitrary-URL tool (threat-model lock)


def test_live_tool_exposes_no_url_or_fetch_target_parameter():
    spec = build_live_resolve_spec(_RecordingClient())
    schema = spec.input_schema
    top_level = set(schema["properties"])
    row_props = set(schema["properties"]["rows"]["items"]["properties"])
    forbidden = {"url", "uri", "source_url", "candidate_url", "fetch_url", "target", "endpoint", "href", "link"}
    assert top_level == {"rows", "source_types"}
    assert not (top_level & forbidden)
    assert not (row_props & forbidden)
    # The row shape is exactly the bounded identity row (plus row_id).
    assert row_props == {"row_id", "vendor_name", "domain", "business_entity_name", "registration_number"}


def test_live_tool_rejects_caller_supplied_url(snapshot):
    # A caller cannot coerce the tool to fetch a URL: an undeclared url field is a
    # schema rejection at the dispatcher; even reaching the func, only identities are
    # forwarded and the transport contacts only the operator endpoint.
    spec = build_live_resolve_spec(_RecordingClient())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"rows": [{"vendor_name": "x", "url": "http://169.254.169.254/"}]}, spec.input_schema)


def test_hosted_client_only_contacts_configured_endpoint(snapshot):
    # The fake transport records every URL; assert each is under the configured base
    # and none is derived from the (URL-free) caller rows.
    transport = _FakeTransport(result={"resolved": []})
    client = HostedTransportClient(endpoint="https://hosted.example/", transport=transport, sleep=lambda _s: None)
    client.resolve([{"vendor_name": "Stripe", "domain": "stripe.com"}], ["dpa"])
    urls = [url for _m, url, _b, _t in transport.calls]
    assert urls[0] == "https://hosted.example/v1/verify"
    assert urls[1].startswith("https://hosted.example/v1/verify/")
    for url in urls:
        assert url.startswith("https://hosted.example/")


# --------------------------------------------------------------------------- credential handling


def test_job_token_sent_only_as_bearer_on_poll_never_on_create():
    transport = _FakeTransport()
    client = HostedTransportClient(
        endpoint="https://hosted.example/", api_key="api-key-123", transport=transport, sleep=lambda _s: None
    )
    client.resolve([{"domain": "vendor.example"}], None)
    create_call = next(c for c in transport.calls if c[0] == "POST")
    poll_call = next(c for c in transport.calls if c[0] == "GET")
    # Create is authorised by the API key, never the job_token (the token doesn't exist yet).
    assert create_call[3] == "api-key-123"
    # Poll is authorised SOLELY by the one-time job_token, not the API key.
    assert poll_call[3] == "secret-cap-token"


def test_resolution_envelope_never_contains_job_token(snapshot):
    # The hosted poll projection (correctly) excludes the token; assert the tool's
    # envelope likewise never carries the job_token, even if a transport regressed.
    resolution = {"state": "completed", "result": {"resolved": []}, "not_advice": True}
    client = _RecordingClient(resolution=resolution)
    out = tools.resolve_vendor_sources(snapshot, client, [{"domain": "vendor.example"}], None)
    blob = json.dumps(out)
    assert "secret-cap-token" not in blob
    assert "job_token" not in blob


def test_client_does_not_log(capsys):
    transport = _FakeTransport()
    client = HostedTransportClient(
        endpoint="https://hosted.example/", api_key="api-key-123", transport=transport, sleep=lambda _s: None
    )
    client.resolve([{"vendor_name": "Stripe"}], None)
    captured = capsys.readouterr()
    # The client performs no logging at all; in particular the token never appears.
    assert "secret-cap-token" not in captured.out + captured.err
    assert "api-key-123" not in captured.out + captured.err


# --------------------------------------------------------------------------- non-advisory


def test_resolution_carries_non_advisory_boundary(snapshot):
    client = _RecordingClient(resolution={"state": "completed", "result": {"resolved": []}, "not_advice": True})
    out = tools.resolve_vendor_sources(snapshot, client, [{"domain": "vendor.example"}], None)
    assert out["not_advice"] is True
    blob = json.dumps(out).lower()
    for banned in ("compliant", "approved", "risk score", "pass/fail", "suitable", "recommend"):
        assert banned not in blob


def test_live_tool_description_is_non_advisory_and_url_free():
    spec = build_live_resolve_spec(_RecordingClient())
    desc = spec.description.lower()
    assert "not advice" in desc
    assert "no url" in desc or "no fetch-target" in desc or "never fetches" in desc
    for banned in ("compliant", "approved", "risk score", "recommend"):
        assert banned not in desc


# --------------------------------------------------------------------------- transport client lifecycle


def test_disabled_kill_switch_response_surfaces_transport_error():
    # A 200 {state: disabled} create (hosted verify kill-switched) is a clean signal,
    # not a job; the client raises so the tool can fall back to the static surface.
    class _DisabledTransport:
        def __call__(self, method, url, json_body, bearer_token):
            return HostedResponse(status=200, body={"state": "disabled", "verify_enabled": False, "not_advice": True})

    client = HostedTransportClient(endpoint="https://hosted.example/", transport=_DisabledTransport(), sleep=lambda _s: None)
    with pytest.raises(HostedTransportError):
        client.resolve([{"domain": "vendor.example"}], None)


def test_non_terminal_job_times_out_bounded():
    transport = _FakeTransport(poll_state="received")  # never terminal
    client = HostedTransportClient(
        endpoint="https://hosted.example/", transport=transport, max_polls=3, sleep=lambda _s: None
    )
    with pytest.raises(HostedTransportError):
        client.resolve([{"domain": "vendor.example"}], None)
    # Bounded: exactly one create + max_polls GETs, no runaway loop.
    assert sum(1 for c in transport.calls if c[0] == "GET") == 3


def test_endpoint_validation_rejects_non_http_and_credentials():
    for bad in ("ftp://hosted.example/", "https://user:pw@hosted.example/", "https://hosted.example/#frag"):
        client = HostedTransportClient(endpoint=bad, transport=_FakeTransport(), sleep=lambda _s: None)
        with pytest.raises(HostedTransportError):
            client.resolve([{"domain": "vendor.example"}], None)


# --------------------------------------------------------------------------- rollback / static canonical


def test_default_registry_excludes_live_tool():
    # With no extra specs (the default) the live tool is NOT in the served surface.
    names = {spec.name for spec in active_tool_specs()}
    assert LIVE_RESOLVE_TOOL_NAME not in names
    assert LIVE_RESOLVE_TOOL_NAME not in {spec.name for spec in TOOL_SPECS}


def test_hosted_endpoint_unconfigured_is_off(monkeypatch):
    monkeypatch.delenv("OPENVA_MCP_HOSTED_ENDPOINT", raising=False)
    assert hosted_endpoint_from_env() is None
    assert build_hosted_client_from_env() is None
    # Blank is also off (not a wildcard / not a misread enable).
    monkeypatch.setenv("OPENVA_MCP_HOSTED_ENDPOINT", "   ")
    assert hosted_endpoint_from_env() is None
    assert build_hosted_client_from_env() is None


def test_hosted_endpoint_configured_builds_client(monkeypatch):
    monkeypatch.setenv("OPENVA_MCP_HOSTED_ENDPOINT", "https://hosted.example/")
    monkeypatch.setenv("OPENVA_MCP_HOSTED_API_KEY", "k")
    client = build_hosted_client_from_env()
    assert isinstance(client, HostedTransportClient)
    assert client.endpoint == "https://hosted.example/"
    assert client.api_key == "k"


def test_static_server_default_surface_unchanged(snapshot):
    # Rollback / canonical: a default-built server (no extra specs) lists exactly the
    # static tool set and never the live tool.
    async def scenario() -> None:
        from mcp.shared.memory import create_connected_server_and_client_session

        server = build_server(snapshot)
        async with create_connected_server_and_client_session(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert LIVE_RESOLVE_TOOL_NAME not in names
            # The static tools are still all present and callable.
            meta = await client.call_tool("get_snapshot_metadata", {})
            assert meta.structuredContent["not_advice"] is True

    pytest.importorskip("mcp")
    anyio.run(scenario)


def test_live_tool_registered_only_when_activated(snapshot):
    # When activated (endpoint configured), the live tool IS published alongside the
    # static surface and resolves over the (fake) transport.
    async def scenario() -> None:
        from mcp.shared.memory import create_connected_server_and_client_session

        spec = build_live_resolve_spec(
            _RecordingClient(resolution={"state": "completed", "result": {"resolved": []}, "not_advice": True})
        )
        server = build_server(snapshot, [spec])
        async with create_connected_server_and_client_session(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert LIVE_RESOLVE_TOOL_NAME in names
            out = await client.call_tool(LIVE_RESOLVE_TOOL_NAME, {"rows": [{"row_id": "1", "domain": "vendor.example"}]})
            assert out.structuredContent["not_advice"] is True
            # A caller-supplied url field is a controlled tool error (threat-model lock).
            bad = await client.call_tool(LIVE_RESOLVE_TOOL_NAME, {"rows": [{"domain": "x", "url": "http://evil/"}]})
            assert bad.isError

    pytest.importorskip("mcp")
    anyio.run(scenario)
