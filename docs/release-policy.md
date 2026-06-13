# Release Policy

This policy defines how OpenVA releases should be prepared, described, and consumed.

OpenVA releases are metadata and tooling releases. They are not legal, compliance, procurement, security, KYC, AML, or vendor-risk certifications.

## Release goals

A release should give downstream consumers a stable point to pin:

- repository tag;
- `openva-pack.json`;
- generated indexes;
- generated registry outputs;
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
indexes/vendor-match-index.json
dist/vendors/*.json
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
dist/vendors/*.json
schemas/openva/*.json
fixtures/packs/**/*.json
```

The manifest is intended for release candidates and release assets. It does not change the pack contract and does not include raw vendor documents.

## Non-technical release downloads

OpenVA distributes non-technical download assets through GitHub Releases, not a hosted website or central upload service.

On tag push for tags matching `v*`, the `release-downloads` workflow generates and attaches:

```text
release-artifacts.json
openva-csv.zip
openva-sample-inventory.csv
openva-inventory-template.csv
openva-release-downloads-manifest.json
```

The workflow has `contents: write` because GitHub requires that permission to attach assets to a release. This is a deliberate least-privilege exception for release distribution only. The workflow is restricted to `v*` tag pushes and must not run on ordinary pushes to `main`.

The download manifest records SHA-256 checksums and sizes for the generated non-technical assets. Release maintainers verify the uploaded assets and checksums rather than generating the assets manually.

## Release readiness checklist

Before tagging a release:

```bash
python -m tools.openva.release_smoke
```

Release candidates default to source-health enforcement. The `release-candidate` workflow downloads the latest successful `source-maintenance-report` artifact for `source-verification-report.json` and the latest successful `source-refinement-scan` artifact for `confirmed-p0-repair-candidates.json`, builds:

```text
release-source-health-readiness.json
release-source-health-summary.md
```

and uploads those readiness artifacts before enforcing the result. Confirmed P0 source-health failures block release candidates by default. Missing, unavailable, or invalid source-health artifacts also block release candidates in enforcement mode. Missing, unavailable, or invalid confirmed-P0 scan artifacts also block release candidates in enforcement mode because the release cannot prove its source-health state.

Ambiguous access and source quality statuses remain warning-only:

```text
bot_protected
forbidden_unknown
gated_or_login_required
homepage_or_generic_redirect
possible_mismatch
suspect_inferred_url
stale verification
```

`report_only` remains available as an explicit diagnostic mode when maintainers need to inspect source-health readiness without blocking a candidate run. It should not be treated as the normal release posture.

### Aggregate source-intelligence release gate (WP35)

Source-health readiness is one constituent of the aggregate release-gate decision. The `release-candidate` workflow first builds the source-health readiness artifact (the producer), then runs the consolidated release gate:

```bash
python -m tools.openva.release_gates check --profile release \
  --source-health-readiness release-source-health-readiness.json \
  --source-health-policy "$SOURCE_HEALTH_POLICY" --enforce
```

The aggregate gate consumes the readiness artifact as one gate and adds export-build, schema, digest-recomputation, advisory-wording, private/gated-leakage, observation-freshness, material-change-surfacing, reversibility, and bot-constitution gates (see `config/release-gates.yaml` and `config/bot-constitution.yaml`). It writes `release-gates.json` and `release-gates-summary.md`, which are uploaded alongside the source-health readiness artifacts. The aggregate release-gate result blocks the release candidate. The `--source-health-policy` flag carries the existing `enforce`/`report_only` choice into the aggregate, so source health can be made diagnostic without disabling the other gates.

The same gate runs in deterministic `--profile pr` form inside the `validate` workflow's `repository-integrity` job: committed-repository checks only, with no network and no dependency on Actions artifacts. The `release` profile additionally requires runtime evidence (the source-health readiness artifact); missing, malformed, or stale required evidence fails closed.

Maintainers may also run the underlying commands individually:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
python -m tools.openva.conformance fixtures/packs/valid-brand-only-fallback
python -m tools.openva.release_artifacts build
python -m tools.openva.release_artifacts check
```

Also verify:

- no generated index diff remains uncommitted;
- `openva-pack.json` is current;
- `indexes/vendor-match-index.json` is current;
- release artifact checksums are available for downstream consumers;
- release download checksums are available for `openva-csv.zip`, `openva-sample-inventory.csv`, and `openva-inventory-template.csv`;
- no raw documents, screenshots, portal exports, private certificates, or extracted full text are committed by default;
- release notes contain no legal, compliance, procurement, security, KYC, AML, or risk advice;
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
OpenVA records are best-effort metadata about public vendor-published sources. They may be incomplete or outdated. OpenVA does not provide legal, compliance, procurement, security, KYC, AML, or vendor-risk advice and does not include bespoke, customer-specific, gated, or private materials.
```
