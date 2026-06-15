# openva-mcp

Local-first, read-only [MCP](https://modelcontextprotocol.io) server over the
OpenVA public export contract. It is a consumer adapter: it reads the static,
digest-verifiable agent export tree and exposes read-only tools. It is not
catalog authority, a hosted service, a risk engine, or a write path.

## Install

```bash
pipx install openva-mcp
# or
pip install openva-mcp
```

## Run

Pinned local snapshot (an OpenVA export or release directory):

```bash
openva-mcp --snapshot /path/to/openva-export
```

Hosted static snapshot (the public export tree):

```bash
openva-mcp --base-url https://thedanieltan.github.io/open-vendor-assurance/public
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
| `match_inventory` | Match inventory rows to vendors (ambiguous/unmatched preserved) |
| `get_snapshot_metadata` | Snapshot identity and catalog counts |
| `verify_snapshot` | Recompute and cross-check every export digest |

## Guarantees

- **Read-only.** No catalog mutation, vendor approval/rejection, GitHub writes,
  risk/security scoring, or compliance/procurement conclusions. No write token.
- **Integrity-first.** Remote data is represented as verified only after its
  content digest matches the agent index; a mismatch fails closed. Cached
  fallback is used only when the exact cached snapshot identity is disclosed.
- **Original URLs preserved.** Every source result keeps the original
  vendor-published URL; ambiguous matches stay ambiguous and unmatched inputs
  stay unmatched.
- **Not advice.** Every result carries `not_advice: true`.

See [`docs/agent-integrations.md`](../../../docs/agent-integrations.md) for host
configuration and framework examples.
