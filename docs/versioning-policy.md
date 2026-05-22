# Versioning Policy

OpenVA uses several version identifiers because different parts of the project change at different speeds.

Consumers should not treat all versions as interchangeable.

## Version identifiers

### Package version

Defined in:

```text
pyproject.toml -> project.version
```

Current value:

```text
0.1.0
```

This is the Python/tooling package version. It describes CLI and developer-tooling maturity, not the legal meaning, accuracy, or completeness of catalog metadata.

### Record schema version

Defined in generated records and indexes as:

```text
schema_version
```

Current value:

```text
0.1.0
```

This version describes OpenVA record and index shape within the `0.1.x` line.

Patch-level increments may add backward-compatible validation, docs, fixtures, or tooling behavior. They must not silently break existing consumers.

### Export profile ID

Defined in `openva-pack.json` as:

```text
profileId: openva.public-metadata.v1
```

The profile ID describes the external consumer contract and project guarantees:

- public sources only;
- metadata first;
- non-advisory;
- raw documents not mirrored by default.

A new `profileId` is required when those guarantees or import expectations materially change.

### Export pack schema version

Defined in `openva-pack.json` as:

```text
schemaVersion: openva-export-pack.v1
```

The export pack schema version describes the machine-readable pack manifest shape.

A new `schemaVersion` is required when the manifest format changes incompatibly for consumers.

## Compatibility rules

### Patch-compatible changes

These may stay within the current `0.1.x` line and current export profile:

- vendor metadata additions;
- source metadata additions;
- artifact metadata additions;
- generated index refreshes;
- documentation changes;
- non-breaking validator improvements;
- non-breaking catalog-agent workflow improvements;
- additional conformance fixtures;
- additional tests;
- observation result documentation improvements;
- typo fixes and wording clarification.

### Schema-version changes

Increment the record `schema_version` when a change affects record or index shape.

Examples:

- adding a required field to vendor/source/artifact/observation/change records;
- removing a field;
- changing a field type;
- changing required enum semantics;
- changing index item shape;
- changing canonical path expectations in a way consumers must handle.

Backward-compatible optional field additions may remain in `0.1.x` only if validators and consumers can safely ignore the field.

### Export schema-version changes

Create a new `schemaVersion` when the pack manifest changes incompatibly.

Examples:

- renaming `profileId`, `schemaVersion`, `packId`, or `generatedAt`;
- removing transition aliases before the transition is complete;
- changing required `indexes` keys;
- changing `guarantees` structure;
- changing index path rules;
- changing pack-level license structure.

### Export profile changes

Create a new `profileId` when the project's consumer-facing guarantees change.

Examples:

- raw documents become mirrored by default;
- private or gated sources are included;
- advisory/risk fields are introduced;
- public-source-only posture changes;
- metadata-first posture changes;
- OpenVA begins producing approval, suitability, compliance, risk, KYC, AML, or procurement conclusions.

Those changes are not expected in the current roadmap.

## Pinning guidance for consumers

Consumers should pin at least:

```text
profileId
schemaVersion
packId
```

Recommended minimum importer check:

```text
profileId == openva.public-metadata.v1
schemaVersion == openva-export-pack.v1
guarantees.public_sources_only == true
guarantees.metadata_first == true
guarantees.non_advisory == true
guarantees.raw_documents_mirrored_by_default == false
```

Consumers that need reproducibility should also pin:

```text
openva-pack.json digest
index file digests
repository commit SHA or release tag
```

## Deterministic pack timestamps

OpenVA pack and generated index timestamps may use a fixed value such as
`1970-01-01T00:00:00Z` to preserve deterministic rebuilds.

This value is not a catalog freshness signal.

Consumers that need freshness or provenance should use:

- the pinned release tag or repository commit SHA;
- source-level `provenance.collected_at`;
- change-level `detected_at`;
- observation-level `observed_at`, where observation records exist.

Do not treat pack-level `generated_at` or `generatedAt` as evidence that
a vendor source was collected, reviewed, updated, or observed at that time.

## Entity Resolution Boundary

Entity resolution is based on public evidence observed at pack generation time or source observation time.

Resolution confidence tiers such as `resolved`, `candidate`, `ambiguous`, and `brand_only_fallback` describe evidentiary quality in the public metadata. They are not legal status, contracting authority, regulatory, procurement, compliance, security, KYC, AML, sanctions, or vendor-risk determinations.

Absence of lifecycle events in a legal entity record means OpenVA has not recorded lifecycle evidence. It does not mean the entity is currently active or unchanged.

## Pre-1.0 caution

OpenVA is currently in the `0.1.x` line.

Before `1.0.0`, maintainers may still refine schemas, tooling, docs, and contribution workflow. Even so, compatibility-impacting changes should be explicit, reviewed, and documented.

## Non-advisory reminder

No version number means that OpenVA certifies, approves, recommends, validates, or scores a vendor.

Versions describe OpenVA's data and tool contract only.
