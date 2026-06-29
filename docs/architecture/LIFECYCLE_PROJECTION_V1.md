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

## Supersession Time

Supersession state is graph-topological in v1. It is derived from admitted
explicit links under the knowledge cutoff, not from `effective_at` date ordering.

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
