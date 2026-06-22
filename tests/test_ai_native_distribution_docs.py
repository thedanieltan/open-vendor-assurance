"""Documentation contract for the AI-native distribution decision.

Locks the positioning so it cannot silently regress: agent-composed distribution is
primary, native clients are secondary, Google Sheets is a reference/fallback, MCP
supports stdio and Streamable HTTP, no production hosted endpoint is claimed, and
the cached-vs-verified and non-advisory semantics stay explicit.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_adrs_exist_and_are_accepted():
    # ADR-0002..0005 were Proposed until PR #398; on merge they become Accepted
    # (their own status rule, mirroring ADR-0001's post-merge Accepted status).
    # ADR-0006 was authored Proposed and became Accepted via its status-change PR.
    decisions = ROOT / "docs/architecture/decisions"
    for adr in (
        "ADR-0002-agent-composed-workspace-integration.md",
        "ADR-0003-remote-mcp-product-surface.md",
        "ADR-0004-workspace-credential-and-action-boundary.md",
        "ADR-0005-native-clients-as-secondary-compatibility-surfaces.md",
        "ADR-0006-hosted-public-read-deployment.md",
    ):
        text = (decisions / adr).read_text(encoding="utf-8")
        assert "**Status:** Accepted" in text
        # No ADR should still claim it is unmerged/Proposed.
        assert "Proposed — becomes Accepted when the PR" not in text


def test_adr_index_lists_all_records_as_accepted():
    index = read("docs/architecture/decisions/README.md")
    for adr in ("ADR-0001", "ADR-0002", "ADR-0003", "ADR-0004", "ADR-0005", "ADR-0006"):
        assert adr in index
    # Every ADR row is Accepted; no row remains Proposed.
    assert index.count("| Accepted |") == 6


def test_roadmap_frames_primary_and_secondary_distribution():
    text = read("docs/roadmap.md")
    assert "Primary distribution:" in text
    assert "Secondary distribution:" in text
    assert "Streamable HTTP" in text
    assert "agent-composed" in text.lower() or "composed by users' existing agents" in text
    # The old "default next step is separate Excel and Word clients" framing is gone.
    assert "Excel and Word clients that consume" not in text


def test_agent_integrations_documents_both_transports_and_primary_model():
    text = read("docs/agent-integrations.md")
    assert "Streamable HTTP" in text
    assert "stdio" in text
    assert "enrich_inventory" in text
    assert "Primary distribution" in text


def test_mcp_readme_is_not_local_only_and_claims_no_production_endpoint():
    text = read("integrations/mcp/openva_mcp/README.md")
    collapsed = " ".join(text.split())  # robust to markdown line wrapping
    assert "Streamable HTTP" in text
    assert "Local-first" not in text
    assert "does not operate a production hosted endpoint" in collapsed
    # cached-vs-verified semantics stay explicit; live verification stays ADR-0001-governed.
    assert "cached" in text.lower()
    assert "ADR-0001" in text


def test_google_sheets_is_positioned_as_secondary_reference_fallback():
    text = read("integrations/google-sheets/README.md").lower()
    assert "secondary compatibility surface" in text
    assert "reference" in text and "fallback" in text
    assert "not the primary distribution path" in text


def test_agent_export_contract_no_longer_denies_mcp_server():
    text = read("docs/agent-export-contract.md")
    assert "No hosted API and no MCP server" not in text
    # determinism and non-advisory guarantees remain (the verify-transport lockstep
    # reconciliation reads "static, deterministic, digest-verifiable files").
    assert "static, deterministic, digest-verifiable files" in text
    assert "no vendor risk scores" in text.lower()


def test_workspace_composition_doc_is_non_advisory_and_host_owned():
    text = read("docs/agent-workspace-composition.md")
    assert "OpenVA does not access the workspace" in text
    assert "not_advice" in text
    for state in ("matched", "ambiguous", "no_match"):
        assert state in text


def test_enrichment_schemas_are_transport_honest():
    # A shared row schema exists, and the request schema is the MCP envelope, not a
    # single wire schema falsely claimed for both /v1 and MCP.
    row = json.loads(read("schemas/openva/agent-enrichment-row.schema.json"))
    request = json.loads(read("schemas/openva/agent-enrichment-request.schema.json"))
    assert "row" in row["title"].lower()
    # MCP request uses top-level `rows`; /v1 uses `vendors` (documented, not the same schema).
    assert request["required"] == ["rows"]
    assert "vendors" in request["description"]
    # The composition doc and resolver API describe the two transport envelopes honestly.
    comp = read("docs/agent-workspace-composition.md")
    assert "agent-enrichment-row.schema.json" in comp
    assert "rows" in comp and "vendors" in comp
    assert "vendors" in read("docs/resolver-api.md")


def test_resolver_api_reframes_enrich_around_agents():
    text = read("docs/resolver-api.md")
    assert "agent-composed" in text.lower()
    assert "enrich_inventory" in text
    # No false claim that native clients are the committed next step.
    assert "delivered in\nlater work" not in text and "are delivered in later work" not in text
