<!-- mcp-name: io.github.thedanieltan/openva -->

# openva-mcp

Local-first, read-only [MCP](https://modelcontextprotocol.io) server over the
OpenVA public export contract. It is a consumer adapter: it reads the static,
digest-verifiable agent export tree and exposes read-only tools. It is not
catalog authority, a hosted service, a risk engine, or a write path.

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
