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
public source references + provenance + snapshot identity
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
- explicitly requested `source_types` (optional; omit for all canonical types).

The request and result shapes are pinned by
[`schemas/openva/agent-enrichment-request.schema.json`](../schemas/openva/agent-enrichment-request.schema.json)
and
[`schemas/openva/agent-enrichment-result.schema.json`](../schemas/openva/agent-enrichment-result.schema.json).

## 4. Interpret

Preserve the match status verbatim:

```text
matched      ambiguous      no_match
```

Rules:

- never collapse `ambiguous` into `matched`;
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
- preserve formulas and unselected rows;
- avoid deleting or reordering user data;
- surface ambiguous rows separately;
- record the snapshot identity when useful.

## 6. Report

The agent should report: rows processed; matched / ambiguous / no-match counts;
source types requested; snapshot identity; any rows it did not modify; and that
OpenVA returns public-source references rather than compliance conclusions.

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
