# Assurance Intelligence Publication

## Purpose

Pillar 4 publishes a deterministic, public-safe view of materialized Assurance Intelligence for the profile:

```text
openva.assurance-intelligence.v1
```

The profile contains exactly:

```text
instrument_state
supersession_state
verification_state
verification_freshness
evidence_set_state
```

Publication consumes Pillar 3 derivative artifacts. It does not recompute states, widen the lifecycle profile, infer assurance facts from source health, or expose internal provenance.

## Flow

```text
maintenance/assurance-intelligence/latest-index.json
maintenance/assurance-intelligence/latest/**/*.json
  -> assurance intelligence publication policy
  -> public/assurance-intelligence.json
  -> site/dist/data/assurance-intelligence.json
  -> release artifact manifest
```

Browser-side code consumes only the public snapshot copied into the compiled site distribution. It never reads `maintenance/assurance-intelligence/` directly.

## Public Contract

The public snapshot schema is:

```text
schemas/openva/assurance-intelligence-public-snapshot.schema.json
```

The publication policy schema and normative policy are:

```text
schemas/openva/assurance-intelligence-publication-policy.schema.json
config/assurance-intelligence-publication-policy.yaml
```

The policy allowlist permits only public projection identity, public timing fields, optional public assurance metadata, and each axis value with its policy-allowed public reason code.

## Published Fields

Each public entry may expose:

```text
assurance_id
vendor_id
assurance_label
assurance_class
framework_id
framework_display_name
projection_profile
effective_at
knowledge_cutoff
next_reevaluation_at
axes.<axis>.value
axes.<axis>.reason_code
```

State labels in the site are direct human-readable renderings of checked-in vocabularies. They are not endorsements, ratings, legal conclusions, or vendor-risk advice.

## Excluded Fields

Publication explicitly excludes:

```text
input_digest
projected_at
policy digests
policy documents
filesystem paths
projection_ref
caused_by
assurance observation IDs
source observation IDs
raw observations
internal manifests
runtime metadata
```

The generator and tests scan public artifacts for these internal terms. A malformed or leaking snapshot fails closed rather than being partially published.

## Determinism

The snapshot is sorted by:

```text
vendor_id
assurance_id
```

Generation reads no system clock and performs no network access. Identical semantic inputs produce byte-identical public output. `projected_at` is operational metadata in Pillar 3 and is not part of the public snapshot.

## Site Integration

The compiled site copies the public snapshot to:

```text
site/dist/data/assurance-intelligence.json
```

Vendor detail shards include the public entries for that vendor. The UI presents the five axes as factual badges:

```text
Instrument
Supersession
Verification
Freshness
Evidence
```

The site also explains that verification is based on admitted assurance observations, freshness describes the age of the decisive verification basis, evidence-set state describes completeness and internal coherence, and source reachability is separate from assurance verification.

If the snapshot is absent or empty, the site renders a safe unavailable state and does not fabricate Assurance Intelligence.

## Release Integration

The release workflow builds:

```text
public/assurance-intelligence.json
```

before site compilation and release-manifest construction. The release artifact manifest treats that public snapshot as a required release-facing artifact. Missing or stale output fails the release gate.

## Failure Behavior

Publication fails closed for:

```text
malformed latest index
malformed projection
unsafe projection reference
missing referenced projection
unsupported profile
implemented-axis mismatch
assurance or vendor identity mismatch
duplicate assurance ID
unknown state value
disallowed public field
internal provenance leakage
```

Invalid maintenance artifacts are not silently omitted or repaired.

## Source Health Boundary

Source-health telemetry remains operational source availability metadata. It is published through the existing source-health snapshot path and does not determine Assurance Intelligence values. A source-health-only change must not alter the Assurance Intelligence public snapshot.

Automated source-content extraction into assurance observations remains deferred future work. It requires a separate explicit evidence-extraction contract and is not implemented by this publication slice.

## Unsupported Capabilities

This publication path does not add API endpoints, MCP methods, acquisition transport, background scheduling, queues, source-to-assurance derivation, evidence extraction, or publication of raw assurance observations.
