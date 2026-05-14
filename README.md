# open-vendor-assurance

A public-source-only, metadata-first registry of vendor-published assurance references.

OpenVA is intended to be a public vendor assurance knowledge substrate. It records public-source factual metadata about vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, KYC/AML statements where public, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## What OpenVA is

OpenVA is:

- public-source-only;
- metadata-first;
- factual and non-advisory;
- native-language-aware;
- provenance-driven;
- hash-friendly;
- exportable through universal packs;
- usable independently of any one runtime or application.

## What OpenVA is not

OpenVA does not:

- mirror raw vendor documents by default;
- include bespoke agreements;
- include authenticated trust-center or customer portal materials;
- include NDA-gated content;
- state that any vendor is compliant, approved, safe, certified, adequate, suitable, or recommended;
- provide tenant-specific risk decisions;
- replace professional, legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice.

## Start here

For contributors and maintainers:

```text
CONTRIBUTING.md
docs/catalog-agent-protocol.md
MAINTAINERS.md
GOVERNANCE.md
SECURITY.md
```

For consumers and downstream importers:

```text
docs/consumer-conformance-fixtures.md
docs/versioning-policy.md
docs/release-policy.md
docs/release-checklist.md
openva-pack.json
indexes/
schemas/openva/
```

For public launch readiness:

```text
docs/public-launch-checklist.md
docs/roadmap.md
docs/triage-policy.md
docs/first-good-issue-policy.md
DISCLAIMER.md
```

## Validate the repository

Run:

```bash
python -m tools.openva.validate validate
pytest -q
```

Before a release or pack-pinning point, also run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

## Architecture stance

OpenVA maintains public-source vendor assurance metadata:

```text
vendor_public_profile
public_source_reference
artifact_reference
source_observation
freshness_status
change_event
```

Consumers of OpenVA own their own operational use of that metadata:

```text
workspace_vendor
vendor_review
risk_decision
approval
private_evidence
audit_event
control_mapping
user-specific obligation impact
```

OpenVA exports consumer-neutral dataset packs. Importing OpenVA data should not be treated as vendor approval, risk acceptance, legal advice, compliance advice, procurement advice, security advice, KYC/AML advice, or regulatory advice.

## Public-source-only rule

If a source requires login, NDA, customer status, sales approval, support ticket access, private portal access, credentialed access, form submission, or anti-bot bypass, it is out of scope.

The repository may record that a public landing page exists. It must not include private contents, private hashes, private summaries, or extracted private text.

## Native-language rule

The native-language source remains authoritative. English summaries are convenience metadata only.

## Default evidence model

The default evidence model is:

```text
source URL + provenance metadata + access classification + rights classification + hash metadata
```

The default evidence model is not:

```text
raw document mirroring
```

## Pack contract

Current export identifiers:

```text
profileId: openva.public-metadata.v1
schemaVersion: openva-export-pack.v1
schema_version: 0.1.0
```

Consumers should pin the release tag or repository commit, `profileId`, `schemaVersion`, `packId`, and pack/index digests where reproducibility matters.

See:

```text
docs/versioning-policy.md
docs/release-policy.md
```

## Project status

OpenVA is in active pre-public-launch development. The schema, validation tooling, generated indexes, universal pack manifest, observation workflow, conformance fixtures, governance docs, and initial seed catalog are available, but the dataset should not be treated as complete.

## Disclaimer

See [DISCLAIMER.md](DISCLAIMER.md).
