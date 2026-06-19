# ADR-0003: Remote Read-Only MCP as a First-Class Agent Transport

- **Status:** Accepted — recorded by merging PR #398.
- **Date:** 2026-06-18 (proposed), 2026-06-18 (accepted)
- **Decision owners:** OpenVA maintainers (human authority required for boundary,
  policy, and positioning changes per `AGENTS.md`).
- **Programme:** WP-OPENVA-AI-NATIVE-DISTRIBUTION-01.

## Context

OpenVA currently exposes deterministic static exports, a local MCP server over
stdio, a cached `/v1` HTTP API, and an in-process live resolver whose future hosted
transport is governed by ADR-0001. Local MCP is useful for reproducibility and
offline operation, but it requires package installation and local configuration.
Agent-composed workspace use (ADR-0002) needs a remotely accessible, standard agent
transport. The MCP implementation must not fork the existing tool registry,
matching rules, source ranking or snapshot semantics.

## Decision

OpenVA supports MCP through two first-class transports backed by **one** tool
registry and implementation authority:

```text
stdio
Streamable HTTP
```

The remote MCP endpoint uses a single Streamable HTTP MCP path, conventionally
`/mcp`. The existing stdio mode remains supported and continues to work with
pinned local or hosted static snapshots.

**This work package implements cached, read-only snapshot tools only.** Live
verification tools remain governed by ADR-0001 and require their own activation
work. This PR builds transport capability and deployment readiness; it does **not**
claim that OpenVA operates a production hosted endpoint.

## Tool surface

All existing tools are preserved: `search_vendors`, `get_vendor`,
`list_vendor_sources`, `get_source`, `get_source_health`, `get_vendor_changes`,
`match_inventory`, `get_snapshot_metadata`, `verify_snapshot`.

One composite tool is added: **`enrich_inventory`**, for agents that have already
read a user-controlled workspace through another connector. It accepts a bounded
batch of vendor-identity rows and an optional source-type filter, and returns, per
row: `match`, `sources`, `primary_source_by_type`, `source_urls_by_type`, `notes`,
plus a disclosed `snapshot` identity and `not_advice: true` on the envelope. Input
order and duplicates are preserved, `row_id` is echoed verbatim, ambiguous stays
ambiguous, and no-match stays no-match. A compatibility `spreadsheet` projection
may remain available on the HTTP surface but is not the canonical agent contract.

The shared, transport-neutral contract is the **row**
(`schemas/openva/agent-enrichment-row.schema.json`); transport envelopes differ by
design — MCP wraps rows under `rows`
(`schemas/openva/agent-enrichment-request.schema.json`) and `/v1/enrich` wraps the
same rows under `vendors`. The per-row result shape is shared
(`schemas/openva/agent-enrichment-result.schema.json`). This is a deliberate,
documented adapter mapping, not one wire schema presented as authoritative for two
incompatible payloads.

## Shared authority

No second primary-source ranker or projection algorithm is introduced. The shared,
dependency-neutral authority is the **projection** —
`openva_vendor_inventory_matcher.enrichment.assemble_enrichment` (canonical-source
filtering, primary-source ranking, URL grouping, and machine-state notes). Both
surfaces call it, so for the **same match decision and the same sources** they
produce an identical projection.

**Matching capability is surface- and data-dependent** — it is not uniformly shared,
because the two surfaces hold different data:

```text
shared projection authority  (assemble_enrichment: filter + rank + notes)
  ├── HTTP /v1 adapter — pack-backed matcher (MatcherIndex.enrich_row / match_one);
  │     resolves registration-number / legal-entity matches; observation-aware
  │     source projection + spreadsheet projection
  └── MCP adapter — snapshot-grade identity matcher (match_identity: domain/name only,
        no legal-entity data); snapshot source projection
```

This is the documented registration-number parity boundary: a registration-number-only
row matches on `/v1` (pack-backed) and is `no_match` on the snapshot, by design. The
MCP adapter must never reimplement `/v1` enrichment, call a localhost `/v1` over HTTP,
import FastAPI route handlers, or invent a different source ranker. The
primary-source ranker (`primary_source_by_type`) lives once in the shared module and
is re-exported by `matcher.py` so the CSV adapter uses the same ranking.

## Transport boundaries

1. Streamable HTTP must not use the deprecated HTTP-plus-SSE transport as the
   primary implementation.
2. Stdio and Streamable HTTP publish equivalent tools and schemas (enforced by a
   parity test).
3. The remote server is read-only; it accepts no GitHub write token, no workspace
   token, exposes no catalogue mutation, and exposes no arbitrary URL-fetch.
4. It logs no vendor identity, request body, or tool argument.
5. It validates incoming Origin/Host according to the MCP transport boundary
   (DNS-rebinding protection on by default).
6. It bounds request size before JSON parsing where practical.
7. It has liveness (`/healthz`) and readiness (`/readyz`) probes.
8. It fails closed on snapshot integrity failure.
9. Non-loopback binding requires BOTH an explicit public-read configuration
   (`OPENVA_MCP_PUBLIC_READ_ENABLED`) AND an explicit Host allow-list
   (`OPENVA_MCP_ALLOWED_HOSTS`); startup fails closed otherwise, so a wildcard bind
   can never start with healthy probes but a `/mcp` that DNS-rebinding protection
   rejects for every Host. The default local binding remains loopback-only.
10. Deployment-level rate limiting and abuse controls are mandatory before public
    activation (a successor work package).

## Access posture

The initial product data is public and read-only. This PR introduces no
user-account or workspace-authorization system. An explicit public-read deployment
mode is supported. Protected remote MCP and OAuth may be introduced later if OpenVA
exposes restricted capabilities, quotas, or user-specific resources; such work must
follow the applicable MCP authorization specification and requires a separate
decision or activation work package.

## Consequences

**Positive**

- Agent hosts can consume OpenVA without local package installation.
- Stdio remains available for reproducibility and offline use.
- One tool contract serves multiple agent hosts; OpenVA does not become dependent
  on one model vendor.

**Negative / new obligations**

- The remote transport creates a public attack surface; Origin validation, request
  bounds, monitoring and rate limits become operational requirements
  (`docs/security/remote-mcp-threat-model.md`).
- Compound compatibility testing is required.
- Registry metadata cannot be published honestly until a public package or remote
  endpoint exists (a successor work package).
