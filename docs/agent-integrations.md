# Agent Integrations

**Primary distribution:** OpenVA's read-only HTTP/MCP capabilities are designed to be composed by a user's existing agent with the workspace connectors that agent already controls. The agent reads the workspace (spreadsheet, database, tickets), sends OpenVA only bounded vendor identities, and writes results back through its own connector. OpenVA never accesses the workspace. See [`agent-workspace-composition.md`](agent-workspace-composition.md) and [ADR-0002](architecture/decisions/ADR-0002-agent-composed-workspace-integration.md).

OpenVA publishes static, digest-verifiable JSON exports (see [`agent-export-contract.md`](agent-export-contract.md)). Ways to consume them programmatically:

- the read-only **MCP server** (`integrations/mcp/openva_mcp`), over **stdio** or **Streamable HTTP**, for MCP hosts and agent frameworks;
- the static exports directly, for any HTTP or file client.

Everything below is read-only. Nothing here approves, scores, ranks, monitors, or makes compliance, procurement, security, suitability, or risk conclusions about any vendor; every result carries `not_advice: true`.

## Transports

The same tool registry and implementation back both transports — there is no tool drift between them ([ADR-0003](architecture/decisions/ADR-0003-remote-mcp-product-surface.md)):

- **stdio** (default) — `--transport stdio`. Best for reproducibility, offline use, and local MCP hosts.
- **Streamable HTTP** — `--transport streamable-http --host 127.0.0.1 --port 8000 --mount-path /mcp`. Read-only tools over `/mcp`, loopback by default; a non-loopback bind requires `OPENVA_MCP_PUBLIC_READ_ENABLED=true` and a Host/Origin allow-list. Liveness/readiness are available at `/healthz` and `/readyz`. This is cached-snapshot, read-only operation; OpenVA does not operate a production hosted endpoint.

## Data modes

Independent of transport, the server reads one snapshot in one of two data modes:

- **Pinned local** — `--snapshot <dir>`: an extracted OpenVA agent-export release bundle or export tree on disk. Reproducible and offline.
- **Hosted static** — `--base-url <url>`: the public export tree over HTTP. Remote data is represented as usable only after its content digest matches the agent index.

The hosted base URL is `<canonical_base_url>/public`, where `canonical_base_url` is the value in `config/publication.yaml`. Pin a `commit_sha` for reproducibility; `get_snapshot_metadata` and `verify_snapshot` expose and check snapshot identity.

## MCP host configuration

```json
{
  "mcpServers": {
    "openva": {
      "command": "openva-mcp",
      "args": ["--snapshot", "/path/to/openva-export"]
    }
  }
}
```

Hosted mode: replace `args` with `["--base-url", "<canonical_base_url>/public"]` using the `canonical_base_url` from `config/publication.yaml`.

## Structured tool adapters

A host that does not consume MCP directly can expose the same operations through its structured-tool interface. Forward each tool name and JSON Schema from `openva_mcp.server.TOOL_SPECS`, dispatch calls to the server, and return each result verbatim so the snapshot identity and `not_advice` flag are preserved.

## Install

Install the three repository packages together, or, on **Linux x86_64 with CPython 3.12 only**, install offline from the attached `openva-mcp-wheelhouse-linux-x86_64-py312.zip`. See the package [README](../integrations/mcp/openva_mcp/README.md). The wheelhouse is not cross-platform; on other systems use the repository install.

## Local Python

```python
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot
from openva_mcp import tools

snapshot = Snapshot.load(LocalSnapshotSource("/path/to/openva-export"))
print(tools.verify_snapshot(snapshot)["verification"]["ok"])
print(tools.get_vendor(snapshot, "github")["vendor"])
```

## Spreadsheet inventory matching

`match_inventory` accepts rows with `domain`, `vendor_name`, `business_entity_name`, or `registration_number`.

For new consumers, collapse identity to:

```text
match
no_match
```

Compatibility surfaces may still expose `matched`, `ambiguous`, and `no_match`. Map them as follows:

```text
matched -> match
ambiguous -> no_match, no_match_reason=multiple_plausible_entities
no_match -> no_match, no_match_reason=no_indexed_openva_match
```

## Agent-composed enrichment (`enrich_inventory`)

`enrich_inventory` is the composite tool for agent-composed workspace workflows.

The agent:

1. reads a user-controlled workspace through its own connector;
2. sends OpenVA bounded vendor-identity rows such as `row_id`, `vendor_name`, `domain`, `business_entity_name`, and `registration_number`;
3. receives indexed public assurance source references;
4. writes selected fields back into the user's spreadsheet, Notion database, ticket, GRC tool, procurement system, or other workspace.

Preferred per-row agent template:

```json
{
  "row_id": "1",
  "input": {
    "vendor_name": "Stripe",
    "business_entity_name": "",
    "domain": "stripe.com",
    "jurisdiction": "",
    "registration_number": "",
    "registered_address": ""
  },
  "identity": {
    "match_status": "match",
    "matched_vendor_id": "stripe",
    "matched_vendor_name": "Stripe",
    "matched_domain": "stripe.com",
    "match_basis": ["indexed_domain"],
    "no_match_reason": null
  },
  "source_references": {
    "dpa": { "status": "indexed", "url": "https://stripe.com/legal/dpa", "title": "Data Processing Agreement" },
    "privacy_notice": { "status": "indexed", "url": "https://stripe.com/privacy", "title": "Privacy Notice" },
    "subprocessors": { "status": "indexed", "url": "https://stripe.com/legal/subprocessors", "title": "Subprocessors" },
    "security_page": { "status": "indexed", "url": "https://stripe.com/security", "title": "Security" },
    "trust_center": { "status": "indexed", "url": "https://stripe.com/trust", "title": "Trust Center" },
    "status_page": { "status": "not_indexed", "url": null, "title": null }
  },
  "notes": [
    "Matched by indexed domain.",
    "Source references are indexed public references, not vendor approval or risk advice."
  ],
  "not_advice": true
}
```

Source-reference statuses:

```text
indexed
not_indexed
gated
unavailable
not_applicable
```

Compatibility fields such as `match`, `sources`, `primary_source_by_type`, and `source_urls_by_type` may remain in machine output for older adapters. New agents should prefer `identity` and `source_references`. The request/result shapes are pinned by [`schemas/openva/agent-enrichment-request.schema.json`](../schemas/openva/agent-enrichment-request.schema.json) and [`schemas/openva/agent-enrichment-result.schema.json`](../schemas/openva/agent-enrichment-result.schema.json). See [`output-templates.md`](output-templates.md) and [`agent-workspace-composition.md`](agent-workspace-composition.md).

## Self-hosted match service

For an HTTP matching endpoint over the same data, run `services/openva_match_service` (see [`openva-match-service-deployment.md`](openva-match-service-deployment.md)). The MCP `match_inventory` tool and the match service share identity-only matching rules. Insufficient evidence returns `no_match`; competing plausible identities should map to `no_match` with `no_match_reason=multiple_plausible_entities` for new consumers.

## Container

The image runs as a non-root user and needs no secrets. It defaults to stdio; it can also serve the read-only tools over Streamable HTTP. Mount the snapshot read-only:

```bash
docker build -f integrations/mcp/openva_mcp/Dockerfile -t openva-mcp .
docker run --rm -i --read-only -v /path/to/openva-export:/snapshot:ro openva-mcp
```

For hosted-static data with caching, add a writable cache mount and `--base-url <canonical_base_url>/public --cache-dir /cache`. For Streamable HTTP, publish a port and set `OPENVA_MCP_TRANSPORT=streamable-http`; a non-loopback bind also needs `OPENVA_MCP_PUBLIC_READ_ENABLED=true` and a Host allow-list. See the package [README](../integrations/mcp/openva_mcp/README.md).
