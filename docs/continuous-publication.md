# Continuous Publication

OpenVA publishes its accepted catalog continuously. It does not use formal catalog releases, version tags, release candidates, or GitHub Release assets as a publication gate.

## Authoritative lifecycle

```text
accepted change
→ pull request validation
→ controlled merge to main
→ generated indexes rebuilt
→ GitHub Pages deployed
```

The current state of `main` is the authoritative current catalog. The hosted site follows the latest successfully deployed accepted commit.

## Snapshot identity

Every published or exported state should identify the exact inputs used through:

- source commit SHA;
- catalog/index generation timestamp;
- schema version;
- pack or manifest digest where available;
- source-level `collected_at` or observation timestamp where applicable;
- output-generation timestamp for a workbook, JSON bundle, or other derived file.

The catalog generation timestamp and output-generation timestamp are different facts. A workbook created today may contain a catalog generated earlier, and an individual source may have been collected before that catalog build.

## Reproducibility

Consumers that require a fixed OpenVA state should pin an exact commit SHA or verified digest. A commit-addressed snapshot is immutable and reproducible without a separate version tag.

Examples:

```text
repository commit: 0123456789abcdef...
catalog generated at: 2026-07-10T08:00:00Z
schema version: 0.1.0
workbook generated at: 2026-07-10T14:30:00Z
```

Consumers should not select a state merely because its timestamp is newer. They should validate the schema and any required digest before importing it.

## Compatibility changes

Catalog additions and source corrections publish through the normal accepted-change lifecycle. Contract changes to schemas, APIs, adapters, matching semantics, or required fields must be identified in the pull request and governed by the compatibility policy.

A compatibility-impacting change does not require a formal release. It requires explicit contract documentation, validation, migration guidance where necessary, and a source commit that downstream consumers can pin.

## Distribution

The public site, browser resolver, machine-readable public files, repository indexes, and self-hosted components consume the accepted repository state. OpenVA does not maintain a parallel catalog in GitHub Releases.

Historical tags or old GitHub Release artifacts, if any exist in repository history, are not part of the active publication model and must not be presented as the current catalog.

## Operational boundary

Continuous publication does not weaken catalog admission or governance. Changes still pass the applicable validation, provenance, public-source, non-advisory, generated-output, and controlled-merge gates before reaching `main`.
