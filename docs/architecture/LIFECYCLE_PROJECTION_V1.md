# Lifecycle Projection V1

Lifecycle projection is the structural contract for deriving a point-in-time view
of an assurance record from repository facts that are already structurally and
semantically valid. It is operational metadata only. It is not legal,
compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.

Slice 3A defines contracts, policy, fixtures, and tests. It does not implement a
projector.

## Bitemporal Model

Projection requests carry three distinct times:

- `effective_at`: the time whose semantic state is being queried.
- `knowledge_cutoff`: the latest repository knowledge allowed as input.
- `projected_at`: when a projection envelope was materialized.

`knowledge_cutoff` prevents later-known facts from leaking into historical
questions. `projected_at` is operational materialization time and must not alter
the semantic result.

`next_reevaluation_at` records the next known time at which a deterministic
projection may change because of stated date boundaries. It is nullable when the
contract has no known future boundary.

## Projection Axes

The v1 projection profile implements exactly two axes:

- `instrument_state`
- `supersession_state`

Verification, freshness, evidence-set, observation causality, and change-event
sequence projection are outside Slice 3A.

## Determination And Value

Each axis separates `determination` from `value`.

For `instrument_state`, `determination: determined` requires a concrete
instrument state. `determination: indeterminate` requires `value: null`.

For `supersession_state`, v1 always uses `determination: determined`. Slice 2
semantic validation rejects unknown targets, self-links, vendor mismatches,
incompatible edges, divergent successors, and cycles before projection. A valid
v1 supersession graph can therefore always produce either `current` or
`superseded`.

## Supersession Topology

The supersession axis is topology-discriminated:

| Topology | Predecessor | Successors | State |
| --- | --- | --- | --- |
| `standalone` | null | empty | `current` |
| `chain_root` | null | one | `superseded` |
| `chain_intermediate` | present | one | `superseded` |
| `chain_tip` | present | empty | `current` |

Divergence is semantic-invalid, so `successor_assurance_ids` has `maxItems: 1`.

## Invalid Inputs

Projection implementations are expected to fail closed with a
`ProjectionInputInvalidError` or equivalent typed failure when structural or
semantic prerequisites are not satisfied. Slice 3A only defines the contract
fixtures for those invalid inputs; it does not implement the exception class.

## Policy Hierarchy

Hard invariants live in schemas and semantic validators. Configurable projection
rules live in `config/assurance-projection-policy.yaml` and are identified by
policy ID, version, and canonical digest.

The v1 policy uses explicit supersession links only. It does not infer
supersession from dates, framework matches, or identifier similarity.

## Vocabulary Separation

`assurance-v1.schema.json` remains the vocabulary for source records,
observations, verification states, freshness, and legacy change-event families.

`assurance-projection-v1.schema.json` defines lifecycle projection vocabulary.
Only the legacy overloaded `instrumentState` definition is deprecated by this
slice. Verification state and verification freshness are not replaced here.

## Date Normalization

Date-only source facts remain date-only under fields such as
`stated_valid_from` and `stated_valid_until`.

Normalized boundaries use separate date-time fields such as
`interval_start_at` and `interval_end_exclusive_at`. This avoids turning a
source date into a misleading midnight timestamp under the same field name.

Inclusive date-only end dates normalize to the next day's midnight UTC as an
exclusive boundary. For example, `stated_valid_until: 2027-01-09` corresponds to
`interval_end_exclusive_at: 2027-01-10T00:00:00Z`.

## Supersession Time

Supersession state is graph-topological in v1. It is derived from records and
explicit links admitted by `knowledge_cutoff`, not from `effective_at` date
ordering. Supersession state is therefore independent of `effective_at`.

## Lifecycle Change-Event Reasons

Lifecycle change events retain the singular `reason_code` field. The reason
records why the newly established axis state was derived, and it is taken from
the new projection axis result.

Reason validation is discriminated by `transition.axis`:

- `instrument_state` events use `instrumentStateReasonCode` from
  `assurance-projection-v1.schema.json`.
- `supersession_state` events use `supersessionStateReasonCode` from
  `assurance-projection-v1.schema.json`.
- Legacy `verification_state`, `verification_freshness`, and `evidence_set`
  events continue to use the legacy event reason vocabulary from
  `assurance-v1.schema.json`.

The current v1 instrument and supersession evaluators produce exactly one
reason code per axis result. A later diff constructor must fail closed if an
axis result has zero or multiple reasons while constructing this singular-reason
event envelope. Changing only the reason, provenance, policy, stated dates,
normalized boundaries, or supersession topology without changing the axis state
value does not itself create a lifecycle transition event.

## Materialization

Latest lifecycle projections are derivative, rebuildable repository artifacts.
They do not make projected state canonical, and they do not modify immutable
assurance records. Canonical inputs remain vendor records, source records,
assurance records, assurance observations, source observations, and the
projection policy.

Slice 3F materializes three derivative artifact families:

- latest projection documents;
- immutable lifecycle change-event documents;
- a deterministic latest-projection index.

The latest-projection index is the visible commit pointer. Persistent
materialization validates all planned documents and paths first, then writes any
new immutable events, then writes or replaces the latest projection, and updates
the latest index last. This index-last order makes reruns after interrupted
writes safe and idempotent without claiming multi-file transactional atomicity.

Materialization modes are explicit:

- `current`: project the supplied current-state request, diff against the latest
  projection when present, write lifecycle events for axis state-value changes,
  then update latest projection and index when persistent projection content
  changes.
- `rebuild`: recompute derivative state from canonical inputs, including policy
  changes. Rebuilds use the same projection and diff semantics; policy, digest,
  provenance, topology, boundary, or other non-state changes update the latest
  projection and index but do not create lifecycle events.
- `scheduled_reevaluation`: execute a caller-requested reevaluation that was
  previously identified as due. It does not infer the current time and does not
  create a scheduler.
- `historical`: compute an on-demand projection without reading or modifying
  latest materialized state. Historical mode writes no projection, no events,
  and no index.

Only `projected_at` changing is a semantic no-op rebuild: the stored projection,
events, and latest index are left unchanged. A policy-only rebuild with
unchanged axis state updates the latest projection and index but emits no event.
When an axis state value changes, the materializer persists the updated latest
projection, the deterministic lifecycle change event or events, and the latest
index.

Latest-state replacement is monotonic for persistent modes. A new latest
projection must not move `effective_at` or `knowledge_cutoff` backward relative
to the existing latest projection. `projected_at` is operational metadata and is
not used for latest-state ordering.

`next_reevaluation_at` is a planning hint, not a scheduled job. Due planning is
pure: a caller supplies an explicit `as_of`, and entries with
`next_reevaluation_at <= as_of` are returned in deterministic order. The planner
does not sleep, poll, enqueue work, update the index, or mark anything complete.
A later knowledge input can still require materialization independently of
`next_reevaluation_at`.

## Out Of Scope

Slice 3A does not add:

- `project_assurance()`;
- temporal evaluation logic;
- supersession graph projection;
- projection diffing;
- event emission;
- acquisition integration;
- verification or freshness axes;
- MCP, API, site, or export changes.
