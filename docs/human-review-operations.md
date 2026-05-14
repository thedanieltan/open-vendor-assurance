# Human Review Operations

OpenVA human review is a lightweight maintainer workflow for deciding what to do with generated reports, review queues, and proposed catalog changes.

It is not a legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk review process.

## Reviewer surfaces

Human reviewers interact with OpenVA through these surfaces:

```text
GitHub Actions artifacts
Markdown reports
JSON reports
GitHub issues
GitHub pull requests
CODEOWNERS review
local CLI commands
```

A separate UI is not required for the current OpenVA phase.

## Why a UI is not required yet

The current review objects are simple and file-based:

- `observation-report.md`
- `observation-report.json`
- `source-refinement-queue.md`
- `source-refinement-queue.json`
- `release-artifacts.json`
- catalog PR diffs

GitHub already provides:

- reviewer assignment;
- PR diffs;
- comments;
- checks;
- artifact downloads;
- issue templates;
- labels;
- audit history.

A dedicated UI should wait until there is repeated reviewer friction that GitHub artifacts and PRs cannot solve.

## When a UI may become useful

Consider a UI only when reviewers need several of these repeatedly:

- queue filtering across many observation reports;
- bulk triage by result type, vendor, region, source domain, or artifact type;
- persistent reviewer assignment outside GitHub;
- side-by-side source comparison;
- reviewer attestations or sign-off history;
- dashboarding across catalog coverage and source quality;
- integration into another product's workspace;
- non-technical reviewers who cannot work comfortably in GitHub.

Until then, avoid creating an additional app surface that duplicates GitHub and increases maintenance cost.

## Reviewer roles

### Source reviewer

Checks whether a public source is still suitable metadata.

May decide:

- keep source unchanged;
- replace with a clearer public vendor-controlled source;
- mark source for later review;
- reject gated or private replacements.

### Language reviewer

Checks non-English source context.

May decide:

- native title/summary is adequate;
- English convenience summary needs correction;
- source requires someone with stronger native-language context;
- source should remain conservative until reviewed.

### Catalog reviewer

Reviews catalog PRs.

May decide:

- approve metadata-only changes;
- request source corrections;
- reject advisory wording;
- reject gated/private materials;
- require index or pack regeneration.

### Release reviewer

Reviews release-candidate outputs.

May decide:

- release candidate passes;
- generated artifacts need regeneration;
- docs/pack/schema mismatch blocks release;
- observation queue contains only non-blocking source-quality work;
- release must wait for a structural fix.

## Review queues

### Observation report

Produced by:

```text
observe-report
```

Artifacts:

```text
observation-report.md
observation-report.json
```

Reviewer focus:

- result counts;
- unsafe or quarantined URLs;
- unexpected result spikes;
- structural failures;
- whether ambiguous results are normal source-quality work.

### Source refinement queue

Produced by:

```bash
python -m tools.openva.source_refinement_queue observation-report.json \
  --markdown-out source-refinement-queue.md \
  --json-out source-refinement-queue.json
```

Reviewer focus:

- `bot_protected`;
- `size_limited`;
- `fetch_failed`;
- `quarantined`;
- suggested operational next action;
- whether a source metadata PR is warranted.

### Release candidate artifacts

Produced by:

```text
release-candidate
```

Artifact:

```text
release-artifacts.json
```

Reviewer focus:

- release smoke passed;
- artifact count looks plausible;
- SHA-256 digests are present;
- pack/index/schema/fixture artifacts are represented;
- no release action was performed automatically.

## Decision states

Use these reviewer states in issues, PR comments, or queue notes:

```text
accepted
needs-source-update
needs-language-review
needs-maintainer-review
needs-catalog-pr
blocked-gated-source
blocked-unsafe-url
blocked-policy-boundary
non-blocking-source-quality
release-blocker
```

## Blocking vs non-blocking

Do not block release candidate on every weak or bot-protected source.

Block only for:

- unsafe URLs;
- policy violations;
- advisory language;
- generated-file drift;
- schema or pack incompatibility;
- release smoke failure;
- conformance fixture failure;
- broken workflow behavior;
- private or gated material exposure;
- structural observation/reporting bugs.

Usually non-blocking:

- a vendor page blocks automated fetches;
- a large public page is size-limited;
- a public page temporarily fails to fetch;
- a better public source may exist but has not been found;
- a non-English summary could be improved later.

## Reviewer checklist for source queues

For each item:

1. Confirm the source URL is public or mark it out of scope.
2. Confirm no login, NDA, form gate, customer portal, or private material is involved.
3. Check whether the source is vendor-controlled or otherwise authoritative.
4. Decide whether the existing source should remain.
5. If changing source metadata, open a small `Catalog:` PR.
6. Do not add advisory wording.
7. Do not bypass access controls.

## Reviewer checklist for release candidates

1. Confirm `release-candidate` workflow passed.
2. Download `release-artifacts.json`.
3. Confirm artifact paths are expected.
4. Confirm SHA-256 and size fields are present.
5. Confirm release smoke did not report generated-file drift.
6. Review observation/source queues for release blockers only.
7. If no blockers exist, proceed to release/tag decision.

## Recommended operating cadence

Before public launch:

```text
weekly observation review
per-PR catalog review
per-release release-candidate review
ad hoc boundary review
```

After public launch:

```text
daily issue triage during first week
weekly observation review
weekly catalog review queue
release-candidate review before each tag
```

## UI decision

Current decision:

```text
No separate UI yet.
```

Reason:

```text
GitHub Actions artifacts + Markdown queues + JSON queues + PR review are enough for the current project scale.
```

Revisit when review volume, reviewer type, or integration requirements exceed GitHub's native workflow.
