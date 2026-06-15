# Agent Integrations

OpenVA publishes static, digest-verifiable JSON exports (see
[`agent-export-contract.md`](agent-export-contract.md)). Two ways to consume
them programmatically:

- the read-only **MCP server** (`integrations/mcp/openva_mcp`), for MCP hosts
  and agent frameworks;
- the static exports directly, for any HTTP or file client.

Everything below is read-only. Nothing here approves, scores, ranks, or makes
compliance, procurement, or risk conclusions about any vendor; every result
carries `not_advice: true`.

## Data modes

The MCP server reads one snapshot, in one of two modes:

- **Pinned local** — `--snapshot <dir>`: an extracted OpenVA agent-export release bundle (or export tree)
  on disk. Reproducible and offline.
- **Hosted static** — `--base-url <url>`: the public export tree over HTTP.
  Remote data is represented as verified only after its content digest matches
  the agent index.

The hosted base URL is `<canonical_base_url>/public`, where
`canonical_base_url` is the value in `config/publication.yaml`. Pin a
`commit_sha` for reproducibility; `get_snapshot_metadata` and `verify_snapshot`
expose and check snapshot identity.

## Claude / MCP host configuration

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

## OpenAI tool usage

Expose the same tools through the OpenAI tools interface by forwarding each
tool's name and JSON Schema (from `openva_mcp.server.TOOL_SPECS`) and dispatching
calls to the server. Each result is returned verbatim, including its `snapshot`
identity and `not_advice` flag.

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

## Self-hosted match service

For an HTTP matching endpoint over the same data, run
`services/openva_match_service` (see
[`openva-match-service-deployment.md`](openva-match-service-deployment.md)). The
MCP `match_inventory` tool and the match service share the same identity-only
matching rules: insufficient evidence stays `no_match`, competing identities
stay `ambiguous`.

## Container

The image runs as a non-root user over stdio and needs no secrets. Mount the
snapshot read-only:

```bash
docker build -f integrations/mcp/openva_mcp/Dockerfile -t openva-mcp .
docker run --rm -i --read-only -v /path/to/openva-export:/snapshot:ro openva-mcp
```

For hosted mode with caching, add a writable cache mount and
`--base-url <canonical_base_url>/public --cache-dir /cache`.
