# Open Vendor Assurance

Open Vendor Assurance (OpenVA) is a public-source-only, metadata-first registry of vendor-published assurance references.

OpenVA records factual metadata about public vendor assurance materials such as data processing addenda, subprocessor lists, trust-center pages, privacy notices, security pages, certification references, public KYC/AML statements, AI/data terms, and related source references.

OpenVA is not a legal, compliance, procurement, audit, security, KYC, AML, sanctions, regulatory, or vendor-risk advice product.

## Scope

OpenVA is:

- public-source-only;
- metadata-first;
- factual and non-advisory;
- native-language-aware;
- provenance-driven;
- hash-friendly;
- exportable through universal packs;
- usable independently of any one runtime or application.

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
docs/agent-control-plane.md
docs/human-review-operations.md
MAINTAINERS.md
GOVERNANCE.md
SECURITY.md
```

For consumers and downstream importers:

```text
GitHub Releases
docs/release-downloads.md
docs/adapter-contract.md
docs/adapter-output-contract.md
docs/consumer-conformance-fixtures.md
docs/versioning-policy.md
docs/release-policy.md
docs/release-checklist.md
openva-pack.json
indexes/
schemas/openva/
```

For public relaunch readiness:

```text
docs/public-launch-checklist.md
docs/roadmap.md
docs/triage-policy.md
docs/first-good-issue-policy.md
DISCLAIMER.md
LICENSE
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

## Automation posture

OpenVA uses automation for repeatable checks and catalog expansion assistance, but catalog changes remain review-gated.

The full workflow inventory lives in `.github/workflows/`. Current public-facing workflow groups are:

```text
validate.yml                         validates PRs and pushes to main
catalog-pr-guard.yml                 enforces Catalog PR boundaries
catalog-agent-pr.yml                 manual agent-generated Catalog PRs for human review
contribution-intake-agent.yml        issue-to-PR intake for bounded catalog updates
catalog-maintenance.yml              scheduled non-mutating maintenance report
source-maintenance-report.yml        scheduled source health and discovery report
observe-report.yml                   read-only observation report
coverage-audit.yml                   catalog breadth/depth audit
release-candidate.yml                release artifact smoke workflow
```

Scheduled maintenance should detect drift and produce artifacts. It should not silently change `main`.

Agent-generated catalog work should enter through pull requests. Human review remains required for source authority, public accessibility, metadata-only compliance, non-advisory wording, and generated pack/index correctness.

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

Pack-level `generated_at` and `generatedAt` values may be fixed to preserve
deterministic rebuilds. They are not a catalog freshness signal; use source,
change, observation, release tag, or repository commit metadata for provenance.

See:

```text
docs/versioning-policy.md
docs/release-policy.md
```

## Release Downloads

For spreadsheet-first users, OpenVA publishes non-technical download assets through GitHub Releases:

```text
openva-csv.zip
openva-sample-inventory.csv
openva-inventory-template.csv
```

`openva-csv.zip` contains curated CSV exports for vendors, sources, artifacts, observations, candidate sources, unavailable sources, and source coverage. The sample and template inventory files show simple `vendor_name`, `business_entity_name`, optional `domain`, optional `jurisdiction`, optional `registration_number`, and optional `registered_address` columns for matching a vendor list against OpenVA.

These files are generated from the tagged repository state. OpenVA does not operate a public upload service or central hosted matching service; users keep their vendor inventories local unless they choose to run their own tooling.

See `docs/release-downloads.md` for a plain-language walkthrough of the release assets.

## Hosted catalog viewer

OpenVA also provides a GitHub Pages catalog viewer for non-dev users.

Hosted catalog viewer: https://thedanieltan.github.io/open-vendor-assurance/

The hosted site is a static, read-only viewer over public OpenVA metadata. It lets users browse the reviewed catalog snapshot, view the live observation feed shell, use the browser-local matcher, and export selected public metadata.

The site does not provide accounts, workspaces, server-side matching, hosted private inventory upload, vendor scoring, vendor approval, or compliance conclusions. Private vendor inventories should remain browser-local, local, or self-hosted inside the user's own environment.

The hosted site is generated as a compiled catalog distribution:

```text
data/meta.json
data/vendor-search.min.json
data/source-types.json
data/coverage-summary.json
data/vendors/{vendor_id}.json
data/observation-feed.json
```

The reviewed catalog is a release snapshot, not a live monitoring feed. The live observation feed shell is non-canonical and remains empty until the observation ledger workflow ships.

For details, see `docs/release-downloads.md` and `site/README.md`.

## Adapters

OpenVA ships small Python adapters for common consumption paths. Install an adapter from the repository checkout, then point it at the pack directory or `openva-pack.json`.

```bash
python -m pip install adapters/python/openva_pack_reader
python -m pip install adapters/python/openva_csv_export
python -m pip install adapters/python/openva_sqlite_export
python -m pip install adapters/python/openva_jsonl_export
python -m pip install adapters/python/openva_vendor_inventory_matcher
```

Available adapters:

```text
openva_pack_reader                  read-only pack, index, and vendor manifest reader
openva_csv_export                   spreadsheet-friendly CSV export
openva_sqlite_export                local SQLite export
openva_jsonl_export                 pipeline-friendly JSONL export
openva_vendor_inventory_matcher     conservative inventory-to-OpenVA matcher
```

Examples:

```bash
python -m openva_csv_export --pack . --out ./openva-csv
python -m openva_sqlite_export --pack . --out ./openva.sqlite
python -m openva_jsonl_export --pack . --out ./openva-jsonl
python -m openva_vendor_inventory_matcher --pack . --input customer_vendors.csv --out matched_vendors.csv
```

The optional match service in `services/openva_match_service/` wraps the pack reader and inventory matcher as a self-hosted HTTP service. OpenVA does not operate a central hosted service.
