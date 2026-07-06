# Resolver-first closeout

This closeout records the resolver-first consolidation of OpenVA after Phases 1-9.
It is a status document, not a new phase and not a hosted-service launch claim.

OpenVA is now positioned as a resolver-first, public-source-only, metadata-first
system for vendor-published assurance source references. The product boundary is
source discovery, classification, source-pack shaping, export, and reusable public
source memory. It is not vendor approval, risk scoring, legal advice, compliance
advice, security advice, procurement recommendation, audit evidence, document
monitoring, or document versioning.

## Completed implementation slices

| Phase | Merged PR | Closeout status |
| --- | --- | --- |
| Phase 1 — Positioning correction | #518 | Public language reframed around resolver-first source packs. |
| Phase 2 — Resolver-first public UI | #520 | Browser entry point moved toward resolving vendor sources and exporting source packs. |
| Phase 3 — Source pack schema | #521 | Public source-pack schema added for human, API, MCP, CSV, spreadsheet, and agent outputs. |
| Phase 4 — Hosted resolver staging | #522 | Staging smoke plan added; no production hosted claim made. |
| Phase 5 — Source map and discovery engine | #523 | Bounded discovery emits locator metadata only. |
| Phase 6 — Candidate memory as background cache | #524 | User-facing reusable-memory states added without exposing internal candidate lifecycle. |
| Phase 7 — Workspace write-back | #525 | Connector-neutral source-pack write-back row projection added. |
| Phase 8 — Configurable source pack builder | #526 | Role concepts became presets for one configurable field-selection view. |
| Phase 9 — Resolver-usefulness prioritisation | #527 | Background cache prioritisation uses resolver-usefulness signals without changing eligibility gates. |

## Current shipped surface

OpenVA currently ships:

- static GitHub Pages browser UI;
- browser-local CSV resolution against loaded public metadata;
- configurable source-pack field selection;
- direct public source lookup;
- static/digest-verifiable agent exports;
- release CSV assets;
- source-pack result schema;
- connector-neutral workspace write-back row projection;
- bounded source-map discovery primitives;
- background candidate memory and reusable-cache prioritisation;
- self-hostable HTTP/MCP/service components.

## Staged or self-hosted, not operated production

The repository contains provider-neutral hosted resolver components and a staging
smoke contract, but OpenVA does not yet claim an operated production hosted
resolver. Hosted live resolver operation remains gated by:

```text
provider
region
domain
credentials
spend controls
staging deployment
production deployment
production smokes
launch evidence
operational ownership
```

Until those gates are complete, use this wording:

```text
OpenVA ships a static/browser-local resolver UI and self-hostable resolver components.
It does not currently operate a production hosted private-inventory upload or live verify endpoint.
```

## Product boundary

In scope:

- resolving bounded vendor identities;
- locating public vendor-published assurance source URLs;
- classifying source types;
- separating found, missing, ambiguous, gated, unavailable, candidate-found, and not-checked states;
- shaping source-pack output for humans, APIs, MCP tools, CSV, spreadsheets, and agents;
- exporting public-source locator metadata;
- background reusable memory through candidate records and controlled PR gates.

Out of scope:

- evaluating document substance;
- approving or rejecting vendors;
- risk scoring;
- legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice;
- private evidence storage;
- authenticated trust-center collection;
- NDA-gated material;
- raw document mirroring by default;
- continuous content monitoring;
- legal document versioning.

## Correct user-facing model

The user-facing model is:

```text
vendor list
  -> choose source fields
  -> resolve public source references
  -> review found / missing / ambiguous / gated / unavailable states
  -> export source pack
  -> optionally write back through the user's own workspace or agent
```

Role labels are presets only:

- CISO preset: security page, trust center, compliance page, vulnerability disclosure, certification references;
- DPO preset: DPA, privacy notice, subprocessor list, data transfer terms, AI/data terms;
- procurement preset: vendor identity, official domain, legal entity hints, source coverage, missing/ambiguous/gated flags, export/write-back status.

Users can include or remove fields. Presets are not separate products, approval paths, or conclusions.

## Internal vocabulary boundary

Internal implementation may still use terms such as candidate, promotion,
reference cache, PR gates, machine-provisional records, release gates, and
workflow authority.

Ordinary user-facing surfaces should prefer:

```text
Resolve vendor sources
Source pack
Choose source fields
Found
Missing
Ambiguous
Gated
Unavailable
Not checked
Queued for reuse
Already known
Candidate found
Not queued: ambiguous
Not queued: unsafe
Not queued: insufficient evidence
Export source pack
```

Avoid presenting internal lifecycle language as the product promise.

## Closeout assertion

The Phases 1-9 roadmap is complete as implementation slices. Future work should
not add new phases casually. The next work should be either:

- operational launch evidence for hosted resolver deployment;
- bug fixes and wording reconciliation;
- tests that prevent drift from the resolver-first boundary;
- user-requested adapter or workspace compatibility work backed by concrete usage.

Every future change should preserve the non-advisory boundary and avoid implying
that OpenVA approves, scores, monitors, certifies, ranks, or recommends vendors.
