# Release Policy

This policy defines how OpenVA releases should be prepared, described, and consumed.

OpenVA releases are metadata and tooling releases. They are not vendor certifications or advisory outputs.

## Release goals

A release should give downstream consumers a stable point to pin:

- repository tag;
- `openva-pack.json`;
- generated indexes;
- schema files;
- conformance fixtures;
- tooling version;
- release artifact checksums.

## Release artifacts

A normal OpenVA release should include:

```text
source repository tag
openva-pack.json
indexes/*.json
schemas/openva/*.json
fixtures/packs/**
release-artifacts.json
release notes
```

Raw vendor documents are not release artifacts by default.

## Release artifact manifest

OpenVA can generate a deterministic release artifact manifest:

```bash
python -m tools.openva.release_artifacts build
python -m tools.openva.release_artifacts check
```

The manifest records:

```text
path
sha256
size_bytes
```

for release-facing artifacts under:

```text
openva-pack.json
indexes/*.json
schemas/openva/*.json
fixtures/packs/**/*.json
```

The manifest is intended for release candidates and release assets. It does not change the pack contract and does not include raw vendor documents.

## Release readiness checklist

Before tagging a release:

```bash
python -m tools.openva.release_smoke
```

Maintainers may also run the underlying commands individually:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
python -m tools.openva.release_artifacts build
python -m tools.openva.release_artifacts check
```

Also verify:

- no generated index diff remains uncommitted;
- `openva-pack.json` is current;
- release artifact checksums are available for downstream consumers;
- no raw documents, screenshots, portal exports, private certificates, or extracted full text are committed by default;
- release notes contain no advisory conclusions;
- release notes distinguish catalog changes from substrate changes;
- any compatibility-impacting change is called out explicitly.

## Release numbering

Use package/repository tags that match the project package version where possible:

```text
v0.1.0
v0.1.1
v0.2.0
```

Pre-1.0 releases may move faster than stable `1.0.0` releases, but compatibility-impacting changes should still be explicit.

## Release note sections

Recommended release note structure:

```text
Summary
Compatibility
Pack profile
Pack schema
Catalog changes
Observation changes
Tooling changes
Governance/docs changes
Conformance fixtures
Release artifact checksums
Known limitations
Upgrade notes
```

## Catalog-only releases

Catalog-only releases may include:

- new vendor metadata;
- updated source URLs;
- updated artifact metadata;
- generated index refreshes;
- refreshed release artifact checksums;
- no schema or pack contract changes.

Catalog-only release notes should not imply vendor approval, verification, recommendation, suitability, adequacy, or risk status.

## Substrate releases

Substrate releases include changes to:

- schemas;
- validators;
- pack contract;
- conformance fixtures;
- observation behavior;
- URL safety;
- workflow/security posture;
- release/versioning policy;
- release artifact generation.

Substrate releases require careful compatibility notes.

## Breaking changes

A release has a breaking change when a conforming consumer of the previous pack contract must change code to continue importing OpenVA.

Examples:

- required pack manifest keys change;
- required index keys change;
- record shape changes incompatibly;
- enum semantics change incompatibly;
- profile guarantees change;
- observation hash semantics change;
- URL safety semantics change in a way that changes accepted/rejected sources.

Breaking changes must be explicitly called out in release notes.

## Consumer pinning guidance

Consumers should pin:

```text
release tag
profileId
schemaVersion
packId
pack digest or commit SHA
release-artifacts.json checksums
```

Consumers should not import a pack merely because it has a newer timestamp.

## Known limitations section

Every release should preserve the limitation that OpenVA is best-effort public metadata.

Suggested wording:

```text
OpenVA records are best-effort metadata about public vendor-published sources. They may be incomplete or outdated. OpenVA is not an advisory product and does not include bespoke, customer-specific, gated, or private materials.
```
