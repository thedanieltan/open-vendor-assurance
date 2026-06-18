"""Authority-boundary tests for the MCP surface (static + behavioural).

These assert the hard boundaries of the agent-composed distribution decision: the
MCP package never acquires a workspace SDK, a workspace OAuth token, or a GitHub
write token; exposes no write, mutation, arbitrary-fetch, or live-verification
tool; and the candidate-intake lane stays inert. They guard against scope creep
that a behavioural test alone would miss.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_PKG = ROOT / "integrations" / "mcp" / "openva_mcp" / "openva_mcp"
for _src in (
    ROOT / "integrations" / "mcp" / "openva_mcp",
    ROOT / "adapters" / "python" / "openva_vendor_inventory_matcher",
    ROOT / "adapters" / "python" / "openva_pack_reader",
):
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from openva_mcp.server import TOOL_SPECS  # noqa: E402

MCP_SOURCES = sorted(p for p in MCP_PKG.glob("*.py"))
MCP_TEXT = "\n".join(p.read_text(encoding="utf-8").lower() for p in MCP_SOURCES)

# Tool names: the exact read-only surface. Nothing implying a write, a mutation, a
# live resolution/verification, or an arbitrary fetch may appear.
EXPECTED_TOOLS = {
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

# Workspace SDKs / clients OpenVA must never import.
FORBIDDEN_WORKSPACE_IMPORTS = (
    "googleapiclient",
    "gspread",
    "google.oauth2",
    "google.auth",
    "msgraph",
    "office365",
    "o365",
    "notion_client",
    "atlassian",
    "jira",
    "slack_sdk",
    "slack_bolt",
    "github3",
    "pygithub",
)

# Token / credential acquisition the read-only surface must never perform.
FORBIDDEN_CREDENTIAL_TOKENS = (
    "oauth",
    "refresh_token",
    "access_token",
    "client_secret",
    "github_token",
    "openva_automerge_token",
)


def test_tool_surface_is_exactly_the_read_only_set():
    assert {spec.name for spec in TOOL_SPECS} == EXPECTED_TOOLS


def test_no_write_mutation_or_live_verbs_in_tool_names():
    forbidden = (
        "create", "update", "delete", "approve", "reject", "promote", "submit",
        "write", "push", "merge", "score", "rank", "risk", "recommend",
        "resolve", "fetch", "crawl", "live", "check",
    )
    for spec in TOOL_SPECS:
        lowered = spec.name.lower()
        assert not any(bad in lowered for bad in forbidden), spec.name


def test_no_workspace_sdk_is_imported():
    assert MCP_SOURCES, "MCP package sources not found"
    for token in FORBIDDEN_WORKSPACE_IMPORTS:
        assert token not in MCP_TEXT, f"workspace SDK reference {token!r} found in MCP package"


def test_no_workspace_or_github_credential_is_accepted():
    for token in FORBIDDEN_CREDENTIAL_TOKENS:
        assert token not in MCP_TEXT, f"credential token {token!r} found in MCP package"


def test_no_catalogue_mutation_path_in_mcp_package():
    for token in ("data/vendors", "git commit", "git push", "create_pull", "maintenance/candidates"):
        assert token not in MCP_TEXT, f"mutation reference {token!r} found in MCP package"


def test_no_arbitrary_url_fetch_tool():
    # The only network path is the hosted-static snapshot read (vendor export tree).
    # No tool accepts a caller-supplied URL to fetch.
    for spec in TOOL_SPECS:
        properties = spec.input_schema.get("properties", {})
        assert "url" not in properties
        assert "uri" not in properties
        assert "endpoint" not in properties


def test_candidate_intake_lane_remains_inert():
    """Issue #393 / candidate-intake stays inert: execution_wired must be false."""
    import yaml

    policy = yaml.safe_load((ROOT / "config" / "automerge-policy.yaml").read_text(encoding="utf-8"))

    def find_candidate_intake(node):
        if isinstance(node, dict):
            if "candidate_intake" in node and isinstance(node["candidate_intake"], dict):
                return node["candidate_intake"]
            for value in node.values():
                found = find_candidate_intake(value)
                if found is not None:
                    return found
        return None

    lane = find_candidate_intake(policy)
    assert lane is not None, "candidate_intake lane not found in automerge policy"
    assert lane.get("execution_wired") is False
