# ADR-0004: Workspace Credentials and Workspace Actions Remain Outside OpenVA

- **Status:** Accepted — recorded by merging PR #398.
- **Date:** 2026-06-18 (proposed), 2026-06-18 (accepted)
- **Decision owners:** OpenVA maintainers (human authority required for boundary,
  policy, and positioning changes per `AGENTS.md`).
- **Programme:** WP-OPENVA-AI-NATIVE-DISTRIBUTION-01.

## Context

An AI agent may combine OpenVA with access to spreadsheets, documents, ticketing
systems, databases or collaboration tools. Without a hard boundary, OpenVA could
gradually become responsible for workspace OAuth, document enumeration, tenant
state, user permissions, write-back, private workflow data, or background workspace
monitoring. That would contradict the repository's public-source, non-workspace
posture (`AGENTS.md`, `docs/public-sources-only.md`).

## Decision

OpenVA is a specialist **read-only public metadata capability**. It receives only
explicitly submitted, bounded vendor-identity fields and requested source types.
The agent host remains responsible for all workspace credentials and workspace
actions.

### Data allowed to enter OpenVA

Allowed: `row_id` (opaque correlation id), `vendor_name`, `domain`,
`business_entity_name`, `registration_number`, requested source types, and a
freshness mode when supported.

Not allowed (and never required): workspace OAuth tokens; file/spreadsheet contents
unrelated to vendor identity; user email; workspace id; spreadsheet id; document
id; sheet name; comments or notes unrelated to identity; private evidence;
contracts; security reports; customer-specific agreements; workspace permission
metadata.

The machine-readable request schema
(`schemas/openva/agent-enrichment-request.schema.json`) sets `additionalProperties:
false` so unrelated workspace columns cannot enter OpenVA even by accident.

### Action boundary

OpenVA may state: *this row matched vendor X*; *these public assurance sources are
recorded for vendor X*; *this snapshot and observation metadata apply*.

OpenVA must not state: *the spreadsheet was updated*; *the Jira ticket was changed*;
*the Notion database was synchronized*; *the user approved the change*; *the vendor
passed review*. Only the agent host can truthfully make workspace-action claims.

### Write authorization

The agent composition instructions distinguish:

1. **Explicit write instruction** (e.g. "add the OpenVA source links to this
   spreadsheet") — the agent may proceed under its host's permission model.
2. **Read or analysis instruction only** (e.g. "review this vendor list") — the
   agent should preview proposed changes and seek approval before modifying the
   workspace.

OpenVA itself does not perform or authorize either action.

### Retention and logging

- OpenVA does not persist workspace input in the cached read-only path.
- Vendor identities and row identifiers must not appear in logs or metric labels.
- Only bounded aggregate operational metrics may persist.
- Tool arguments and request bodies must not be emitted in exception traces.
- Correlation identifiers remain opaque and must not be interpreted as workspace
  identifiers.

## Consequences

**Positive**

- Workspace credentials remain with the existing agent host.
- OpenVA avoids broad tenant and identity infrastructure.
- Private workspace contents remain outside OpenVA; the authority boundary is easy
  to audit.

**Negative**

- OpenVA cannot guarantee workspace write quality.
- Different hosts may require different confirmation flows.
- End-to-end testing must involve external agent-host capabilities (a successor
  work package).
