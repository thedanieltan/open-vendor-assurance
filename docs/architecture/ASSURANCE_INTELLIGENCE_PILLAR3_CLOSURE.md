# Assurance Intelligence Pillar 3 Closure

Operational metadata only. Nothing here is legal, compliance, procurement,
security, KYC, AML, audit, vendor-risk advice, scoring, ranking, approval, or a
recommendation.

## Completed Profile

Pillar 3 is closed around the separate profile:

```text
openva.assurance-intelligence.v1
```

The implemented axis order is fixed:

```text
instrument_state
supersession_state
verification_state
verification_freshness
evidence_set_state
```

The lifecycle profile remains separate and unchanged:

```text
openva.assurance-lifecycle.v1
instrument_state
supersession_state
```

## Canonical And Derivative Data

Canonical inputs are assurance records, assurance observations, vendor records,
source records, and checked-in policy documents.

Derivative and rebuildable artifacts are latest intelligence projections, latest
intelligence indexes, and lifecycle change-event documents. Latest projections
are operational commit pointers over canonical facts; they do not replace or
modify immutable assurance records or assurance observations.

## Policy Identities

Unified intelligence projections cite four policy identities:

- lifecycle projection policy
- verification-state policy
- verification-freshness policy
- evidence-set policy

Each identity carries an ID, version, and canonical JSON SHA-256 digest. A
request whose policy identities do not match the supplied policy documents
fails closed.

## Bitemporal Semantics

`effective_at` selects the semantic time being evaluated. `knowledge_cutoff`
limits which records and observations may be known. `projected_at` is
operational metadata only and does not affect semantic input digests, event
identity, or materialized no-op rebuild detection.

## Events And Materialization

Unified intelligence diffing emits an immutable change event only when an axis
`value` changes. Changes only to reasons, provenance, policy identity, digests,
normalized boundaries, or `projected_at` do not create events.

Initial persistent materialization emits one event per implemented axis. Rebuild
mode uses the same diff semantics as current materialization; it does not invent
special event meanings.

## Rebuild And Recovery Guarantees

All latest intelligence artifacts are rebuildable from canonical inputs and
policies. Immutable events are not deleted during rebuild. Reapplying the same
materialization plan is idempotent: identical existing events are treated as
already present, while an existing event ID with different content fails closed.

Persistent writes use index-last commit semantics:

```text
validate everything
write immutable events
write latest projection
write latest index last
```

This does not claim multi-file transactional atomicity. Instead, interrupted
states are recovered by deterministic event IDs, idempotent event writes, and
the latest index acting as the visible commit pointer.

## Source Observation Boundary

Source observations are Pillar 2 operational telemetry about retrieval,
reachability, access posture, hashes, and source-health/change signals. They do
not directly or indirectly determine:

- `verification_state`
- `verification_freshness`
- `evidence_set_state`

HTTP status, fetch failure, source availability, source-health status, redirects,
and content transport metadata are not assurance evidence. Assurance intelligence
consumes assurance observations, not raw source observations.

## Deferred Extraction Subsystem

Automated source-content extraction remains deferred future work. It requires a
separate explicit evidence-extraction contract that defines:

- eligible source-observation inputs;
- machine-readable extracted facts;
- target-assurance linkage;
- provenance into assurance observations;
- policy-governed mappings;
- fail-closed unsupported-input behavior.

Until that subsystem exists, source observations must not be converted into
assurance observations by inference, filename matching, URL interpretation,
HTTP status, source-health status, or free-text interpretation.

## Pillar 4 Boundary

Pillar 3 produces internal derivative intelligence artifacts only. API, MCP,
site, export, publication, scheduling, notification, and distribution surfaces
belong to later work and are not implemented by Pillar 3 closure.
