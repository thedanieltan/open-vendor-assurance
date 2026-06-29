# Temporal Assurance Schema v1

OpenVA's temporal assurance registry is a structural metadata contract for
public-source-backed assurance claims and observations. It records provenance,
shape, and non-advisory state labels only. It does not determine legal
compliance, certification validity, procurement suitability, vendor risk, or
security adequacy.

## Four-layer model

The registry separates four layers:

1. Vendor identity identifies the catalog vendor.
2. Source references describe public source surfaces and access state.
3. Assurance records describe one public assurance instrument or vendor
   assertion for one vendor.
4. Assurance observations record point-in-time evaluations of an assurance
   record against source-observation evidence.

Assurance records cite source-reference IDs. They do not embed URLs, retrieved
content, source health, HTTP status, redirects, hashes, or bot-protection
signals. Those remain in source-level records.

## Records and events

An assurance record is immutable descriptive data for one instrument or
assertion. Renewals are represented as separate assurance records, optionally
linked with `supersedes_assurance_id`; historical records are not overwritten.

Assurance observations are append-only point-in-time records. They may record
observed claim fields, extraction method, policy, claim presence, and
verification outcome, but they do not contain lifecycle transition `from` or
`to` states.

Assurance change events are also append-only. They describe lifecycle projector
output using a typed transition axis, reason code, causal record IDs, and
policy. Slice 1 defines only this event structure; it does not implement the
projector.

## Source access versus assurance state

Source health and assurance state are separate. Missing, gated, bot-protected,
unparseable, or inaccessible evidence can be represented as observation
outcomes or reason codes, but it does not structurally imply expiry,
withdrawal, non-compliance, or any current-state conclusion.

Acquisition provenance is not assurance evidence. Assurance evidence references
source IDs and source-observation IDs rather than raw acquisition artifacts.

## Class-specific temporal shapes

The assurance record schema uses a root `oneOf` and a closed vocabulary
discriminator for four assurance classes:

- `accredited_certification` requires an issuer, at least one non-null
  identifier, and certification validity dates `valid_from` and `valid_until`.
- `attestation_report` requires an issuer and exactly one of `as_of_date` or
  `reporting_period`; no expiry is inferred.
- `regulatory_assertion` permits only nullable claimed dates and may have no
  intrinsic temporal date.
- `contractual_capability` permits nullable claimed effective dates and optional
  textual conditions.

The vocabulary intentionally has no `hipaa_certified` assurance class and the
schemas do not expose generic advisory booleans such as `compliant`, `safe`, or
`approved`.

## Structural boundary

Slice 1 validates presence, shape, closed vocabularies, class isolation,
forbidden fields, append-only record shapes, and the explicit
`non_advisory` boundary.

It does not validate:

- vendor existence;
- source existence;
- source and vendor compatibility;
- date ordering;
- supersedes target existence;
- registry authority sufficiency;
- source-access implications;
- lifecycle projection;
- continuity inference;
- current-state projection.

For example, a certification record with `valid_from` after `valid_until` is
structurally valid in Slice 1. A later semantic validation layer may reject it.

## Offline vocabulary resolution

The assurance schemas reference the versioned
`schemas/openva/vocabularies/assurance-v1.schema.json` resource. The
production schema registry loads all assurance schemas locally, checks them with
Draft 2020-12, registers their `$id` values with `referencing`, and resolves
references offline. Validation must never retrieve `https://openva.dev/...`
schema resources over the network.

## No continuity inference

The schema structure does not represent continuity inference. Separate records,
observations, and change events can describe what was observed and what a
projector derived, but absence of a newer record or observation does not imply
ongoing validity, expiry, withdrawal, or non-compliance.
