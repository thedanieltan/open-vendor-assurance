# Agent Integrations

**Primary distribution:** OpenVA's read-only HTTP/MCP capabilities are designed to
be composed by a user's existing agent with the workspace connectors that agent
already controls. The agent reads the workspace (spreadsheet, database, tickets),
sends OpenVA only bounded vendor identities, and writes results back through its own
connector. OpenVA never accesses the workspace. See
[`agent-workspace-composition.md`](agent-workspace-composition.md) and
[ADR-0002](architecture/decisions/ADR-0002-agent-composed-workspace-integration.md).

OpenVA publishes static, digest-verifiable JSON exports (see
[`agent-export-contract.md`](agent-export-contract.md)). Ways to consume them
programmatically:

- the read-only **MCP server** (`integrations/mcp/openva_mcp`), over **stdio** or
  **Streamable HTTP**, for MCP hosts and agent frameworks;
- the static exports directly, for any HTTP or file client.

Everything below is read-only. Nothing here approves, scores, ranks, or makes
compliance, procurement, or risk conclusions about any vendor; every result
carries `not_advice: true`.

## Transports

The same tool registry and implementation back both transports — there is no
tool drift between them ([ADR-0003](architecture/decisions/ADR-0003-remote-mcp-product-surface.md)):

- **stdio** (default) — `--transport stdio`. Best for reproducibility, offline use,
  and local MCP hosts.
- **Streamable HTTP** — `--transport streamable-http --host 127.0.0.1 --port 8000
  --mount-path /mcp`. Read-only tools over `/mcp`, loopback by default; a
  non-loopback bind requires `OPENVA_MCP_PUBLIC_READ_ENABLED=true` and a Host/Origin
  allow-list. Liveness/readiness at `/healthz` and `/readyz` (readiness fails closed
  until the snapshot verifies). This is cached-snapshot, read-only operation; OpenVA
  does not operate a production hosted endpoint, and live verification is governed
  separately by ADR-0001.

## Data modes

Independent of transport, the server reads one snapshot in one of two data modes:

- **Pinned local** — `--snapshot <dir>`: an extracted OpenVA agent-export release bundle (or export tree)
  on disk. Reproducible and offline.
- **Hosted static** — `--base-url <url>`: the public export tree over HTTP.
  Remote data is represented as verified only after its content digest matches
  the agent index.

The hosted base URL is `<canonical_base_url>/public`, where
`canonical_base_url` is the value in `config/publication.yaml`. Pin a
`commit_sha` for reproducibility; `get_snapshot_metadata` and `verify_snapshot`
expose and check snapshot identity.

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

Hosted mode: replace `args` with
`["--base-url", "<canonical_base_url>/public"]` (the `canonical_base_url` from
`config/publication.yaml`).

## Structured tool adapters

A host that does not consume MCP directly can expose the same operations through
its structured-tool interface. Forward each tool name and JSON Schema from
`openva_mcp.server.TOOL_SPECS`, dispatch calls to the server, and return each
result verbatim so the `snapshot` identity and `not_advice` flag are preserved.

## Install

Install the three repository packages together (online dependency resolution),
or, on **Linux x86_64 with CPython 3.12 only**, install offline from the
attached `openva-mcp-wheelhouse-linux-x86_64-py312.zip`. See the package
[README](../integrations/mcp/openva_mcp/README.md). The wheelhouse is not
cross-platform; on other systems use the repository install.

## Local Python

```python
from openva_mcp.snapshot import LocalSnapshotSource, Snapshot
from openva_mcp import tools

snapshot = Snapshot.load(LocalSnapshotSource("/path/to/openva-export"))
print(tools.verify_snapshot(snapshot)["verification"]["ok"])
print(tools.get_vendor(snapshot, "github")["vendor"])
```

## LangChain

Wrap each entry in `TOOL_SPECS` as a `StructuredTool` whose function calls the
corresponding `openva_mcp.tools` function with a loaded snapshot. Preserve the
returned `snapshot` and `not_advice` fields in tool output.

## LlamaIndex

Register the same functions as `FunctionTool`s in a `ToolSpec`, sharing one
loaded snapshot across calls. Use `verify_snapshot` before trusting remote data.

## n8n

Run the server in a container and call it from an MCP node, or call the static
exports directly with an HTTP Request node starting at
`/public/openva-agent-index.json` and following the listed `export_path`s.

## Spreadsheet inventory matching

`match_inventory` accepts rows with `domain`, `vendor_name`, or
`business_entity_name`. Each row's `match_status` is `matched`, `ambiguous`
(with candidates), or `no_match`. For a file-based CSV workflow use the
`openva-vendor-inventory-matcher` adapter, which uses the same vocabulary.

## Agent-composed enrichment (`enrich_inventory`)

`enrich_inventory` is the composite tool for agent-composed workspace workflows: an
agent that has read a workspace through its own connector sends a bounded batch of
vendor-identity rows (`row_id`, `vendor_name`, `domain`, `business_entity_name`,
`registration_number`) plus optional `source_types`, and receives, per row, the
match, canonical public sources, the primary source per type, source URLs per type,
and machine-state notes — with input order, duplicates, and exact `row_id`
preserved. It delegates to the same shared authority as the match service
`/v1/enrich`, so the two surfaces agree. The request/result shapes are pinned by
[`schemas/openva/agent-enrichment-request.schema.json`](../schemas/openva/agent-enrichment-request.schema.json)
and
[`schemas/openva/agent-enrichment-result.schema.json`](../schemas/openva/agent-enrichment-result.schema.json).
See [`agent-workspace-composition.md`](agent-workspace-composition.md) for the full
read → enrich → preview → write-back workflow.

## Self-hosted match service

For an HTTP matching endpoint over the same data, run
`services/openva_match_service` (see
[`openva-match-service-deployment.md`](openva-match-service-deployment.md)). The
MCP `match_inventory` tool and the match service share the same identity-only
matching rules: insufficient evidence stays `no_match`, competing identities
stay `ambiguous`.

## Container

The image runs as a non-root user and needs no secrets. It defaults to stdio; it
can also serve the read-only tools over Streamable HTTP. Mount the snapshot
read-only:

```bash
docker build -f integrations/mcp/openva_mcp/Dockerfile -t openva-mcp .
docker run --rm -i --read-only -v /path/to/openva-export:/snapshot:ro openva-mcp
```

For hosted-static data with caching, add a writable cache mount and
`--base-url <canonical_base_url>/public --cache-dir /cache`. For Streamable HTTP,
publish a port and set `OPENVA_MCP_TRANSPORT=streamable-http` (a non-loopback bind
also needs `OPENVA_MCP_PUBLIC_READ_ENABLED=true` and a Host allow-list) — see the
package [README](../integrations/mcp/openva_mcp/README.md).
