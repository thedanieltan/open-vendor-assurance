# Agent Workspace Composition

This document is normative for agent-composed use of OpenVA. It describes how an AI
agent combines OpenVA's read-only vendor resolution with the workspace connector
the agent host already controls.

**OpenVA does not access the workspace.** It receives only bounded vendor-identity
fields and requested source types, and returns public-source references with
provenance and a snapshot identity. The agent host owns workspace authentication,
reading, layout interpretation, user approval, and write-back. See
[ADR-0002](architecture/decisions/ADR-0002-agent-composed-workspace-integration.md)
and [ADR-0004](architecture/decisions/ADR-0004-workspace-credential-and-action-boundary.md).

```text
user's existing workspace
        ↓  (agent host's connector — OpenVA never sees this)
agent reads the relevant table / range / database / section
        ↓
agent maps identity columns → bounded vendor identities
        ↓
OpenVA enrich_inventory  (MCP)  /  POST /v1/enrich  (HTTP)
        ↓
identity + source_references + compatibility projection + snapshot identity
        ↓
agent preview or host-authorised write-back
```

## 1. Read

The agent uses its existing workspace connector to read **only** the relevant
table, range, database, or document section. OpenVA is not involved in this step.

## 2. Detect identity fields

Map likely columns to the bounded identity fields OpenVA accepts:

```text
vendor_name
domain
business_entity_name
registration_number
```

Do not send unrelated columns to OpenVA. The request schema rejects unknown fields
(`additionalProperties: false`).

## 3. Enrich

Call `enrich_inventory` (MCP) or `POST /v1/enrich` (HTTP) with:

- an opaque `row_id` per row (a correlation id, never a workspace identifier);
- bounded vendor identities;
- explicitly requested `source_types` (optional; omit for all indexed types).

The genuinely shared, transport-neutral contract is the **row**, pinned by
[`schemas/openva/agent-enrichment-row.schema.json`](../schemas/openva/agent-enrichment-row.schema.json).
The two surfaces wrap the same rows in transport-specific envelopes — a deliberate,
documented adapter mapping, not one wire schema for both:

- **MCP `enrich_inventory`** takes the rows under a top-level `rows` array
  ([`agent-enrichment-request.schema.json`](../schemas/openva/agent-enrichment-request.schema.json)).
- **HTTP `/v1/enrich`** takes the same rows under a `vendors` array (see
  [`resolver-api.md`](resolver-api.md) and the service's generated OpenAPI).

The per-row result shape is shared and pinned by
[`schemas/openva/agent-enrichment-result.schema.json`](../schemas/openva/agent-enrichment-result.schema.json).
That schema treats `identity` and `source_references` as first-class required
fields for new agents, not tolerated extension fields. The older `match`,
`sources`, `primary_source_by_type`, and `source_urls_by_type` fields remain in
the schema as compatibility projections for existing consumers.
Registration-number matching is data-dependent, not transport-dependent: both
surfaces use one shared legal-entity fallback and match a `registration_number` when
the underlying data carries legal entities for the vendor (the pack for `/v1`; each
vendor export's `legal_entities` for the MCP snapshot). The shipped catalogue carries
no legal-entity records yet, so a registration-number-only row currently resolves to
`no_match` on both surfaces until such data exists.

## 4. Interpret

For new agent consumers, prefer the normalized blocks:

```text
identity
source_references
```

`identity.match_status` is one of:

```text
match
no_match
```

Ambiguity is not a third top-level identity status. It is represented as:

```json
{
  "match_status": "no_match",
  "no_match_reason": "multiple_plausible_entities"
}
```

`source_references` is a destination-neutral object keyed by requested source type.
It is designed for agents that write into different schemas such as Google Sheets,
Notion, Jira, GRC tools, procurement systems, and internal databases.

Example source reference:

```json
{
  "dpa": {
    "status": "indexed",
    "source_type": "dpa",
    "url": "https://vendor.example/legal/dpa",
    "title": "Data Processing Agreement",
    "source_id": "example-dpa"
  },
  "trust_center": {
    "status": "not_indexed",
    "source_type": "trust_center",
    "url": null,
    "title": null,
    "source_id": null
  }
}
```

`source_references.<type>.status` is one of:

```text
indexed
not_indexed
gated
unavailable
not_applicable
```

Compatibility fields remain available for older adapters:

```text
match
sources
primary_source_by_type
source_urls_by_type
```

Rules:

- preserve `identity.match_status` as `match` or `no_match`;
- use `identity.no_match_reason=multiple_plausible_entities` when older compatibility output says `match.status=ambiguous`;
- never treat `no_match` as unsafe or non-compliant;
- never treat a missing source type as non-compliance — it is a neutral coverage
  fact;
- disclose the cached snapshot identity;
- preserve original source URLs;
- preserve `not_advice`.

OpenVA returns public-source references, not compliance, suitability, approval, or
risk conclusions.

## 5. Preview and write

When the user **explicitly asked for modification**, the agent may write through its
workspace connector, subject to host policy. When the user requested **review or
analysis only**, preview proposed changes before modifying the workspace.

The agent should:

- add new fields rather than overwrite unrelated data;
- reuse existing OpenVA fields where unambiguous;
- map `source_references.<type>.url` into the destination's own schema;
- preserve formulas and unselected rows;
- avoid deleting or reordering user data;
- surface no-match rows separately;
- record the snapshot identity when useful.

## 6. Report

The agent should report: rows processed; match / no-match counts; source types
requested; snapshot identity; any rows it did not modify; and that OpenVA returns
public-source references rather than compliance conclusions.

## 7. Example prompts

These illustrate agent composition; they are **not** claims that OpenVA integrates
directly with these platforms.

```text
Review the vendors in this spreadsheet and add their public DPA,
subprocessor, privacy, security and trust-centre references.
```

```text
Match the suppliers in this Notion database against OpenVA.
Preview the proposed source fields before changing the database.
```

```text
For the vendors attached to these Jira issues, retrieve public assurance
references and add a comment only where the vendor match is unambiguous.
```

In each case the agent host's connector performs the reads and writes; OpenVA only
resolves identities and returns public-source metadata.
