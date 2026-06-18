<!-- mcp-name: io.github.thedanieltan/openva -->

# openva-mcp

Read-only [MCP](https://modelcontextprotocol.io) server over the OpenVA public
export contract, available over **stdio** and **Streamable HTTP**. It is a
consumer adapter: it reads the static, digest-verifiable agent export tree and
exposes read-only tools. It is not catalog authority, a risk engine, or a write
path, and it holds no GitHub or workspace credential. OpenVA does not operate a
production hosted endpoint; the Streamable HTTP transport is something you run
yourself (loopback by default), and a non-loopback bind is opt-in.

This server is the agent-composed integration surface described in
[`docs/agent-workspace-composition.md`](../../../docs/agent-workspace-composition.md):
an agent reads a user's workspace through its own connector and sends OpenVA only
bounded vendor identities. See
[ADR-0003](../../../docs/architecture/decisions/ADR-0003-remote-mcp-product-surface.md)
for the transport decision.

## Install

This package and its sibling adapter packages are not yet published to PyPI, so
install all three from the repository together (their dependencies resolve to
the local copies):

```bash
pip install \
  ./adapters/python/openva_pack_reader \
  ./adapters/python/openva_vendor_inventory_matcher \
  ./integrations/mcp/openva_mcp
```

Windows PowerShell (one line):

```powershell
pip install ./adapters/python/openva_pack_reader ./adapters/python/openva_vendor_inventory_matcher ./integrations/mcp/openva_mcp
```

### Offline wheelhouse (Linux x86_64, CPython 3.12)

The release attaches `openva-mcp-wheelhouse-linux-x86_64-py312.zip`, resolved on
Ubuntu with CPython 3.12. It is **not** cross-platform. Extract it and install
with no network:

```bash
unzip openva-mcp-wheelhouse-linux-x86_64-py312.zip -d wheelhouse
pip install --no-index --find-links wheelhouse openva-mcp==0.1.0
```

On other operating systems or Python versions, install from the repository with
normal online dependency resolution (the multi-package command above).

After publication (not yet available), `pipx install openva-mcp` will work
directly. Until then, the bare `pipx install openva-mcp` cannot resolve the
unpublished dependencies.

## Run

Pinned local snapshot (an OpenVA export tree or extracted agent-export release bundle):

```bash
openva-mcp --snapshot /path/to/openva-export
```

Hosted static snapshot (the public export tree; the base URL is the
`canonical_base_url` from `config/publication.yaml` plus `/public`):

```bash
openva-mcp --base-url <canonical_base_url>/public
```

Verify a snapshot and exit:

```bash
openva-mcp --snapshot /path/to/openva-export --verify
```

Remote (Streamable HTTP) mode — read-only tools over `/mcp`, loopback by default:

```bash
openva-mcp --snapshot /path/to/openva-export --transport streamable-http --host 127.0.0.1 --port 8000 --mount-path /mcp
```

A non-loopback bind is refused unless **both** `OPENVA_MCP_PUBLIC_READ_ENABLED=true`
(or `--public-read`) **and** an explicit `OPENVA_MCP_ALLOWED_HOSTS` are set — startup
fails closed otherwise, so a wildcard bind can never come up with healthy probes but a
`/mcp` that DNS-rebinding protection rejects for every Host. Configure
`OPENVA_MCP_ALLOWED_ORIGINS` too for browser clients. Both transports publish
the **same** tools and schemas. Liveness and readiness are exposed at `/healthz`
and `/readyz`; readiness fails closed until the snapshot has verified. This PR ships
cached, read-only snapshot tools only — live verification is governed separately by
[ADR-0001](../../../docs/architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md).

## Tools

| Tool | Purpose |
| --- | --- |
| `search_vendors` | Find vendors by id, name, or domain |
| `get_vendor` | Vendor identity, domains, status, sources |
| `list_vendor_sources` | A vendor's sources with original URLs and health |
| `get_source` | A single source record |
| `get_source_health` | Latest observed health and timestamp |
| `get_vendor_changes` | Latest recorded change events |
| `match_inventory` | Match inventory rows to vendors (`match_status`: `matched` / `ambiguous` / `no_match`) |
| `enrich_inventory` | Match a bounded batch of vendor-identity rows and attach their public sources, optionally filtered by `source_type`. For agent-composed workspace workflows; preserves order, duplicates, and exact `row_id`. |
| `get_snapshot_metadata` | Snapshot identity and catalog counts |
| `verify_snapshot` | Recompute and cross-check every export digest |

## Guarantees

- **Read-only.** No catalog mutation, vendor approval/rejection, GitHub writes,
  risk/security scoring, or compliance/procurement conclusions. No write token.
- **Integrity-first.** Remote data is represented as verified only after its
  content digest matches the agent index; a mismatch fails closed. Cached
  fallback is used only when the exact cached snapshot identity is disclosed.
- **Original URLs preserved.** Every source result keeps the original
  vendor-published URL; ambiguous matches stay `ambiguous` and rows with no
  confident match stay `no_match`.
- **Not advice.** Every result carries `not_advice: true`.

See [`docs/agent-integrations.md`](../../../docs/agent-integrations.md) for host
configuration and framework examples.
