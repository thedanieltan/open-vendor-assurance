# Source Trust Operations Runbook

This runbook explains how maintainers operate OpenVA source trust after the Layer 1 through Layer 5 source-health work. It is operational guidance for public-source metadata. It is not legal, compliance, procurement, security, KYC, AML, audit, or vendor-risk advice.

## Weekly Operating Cycle

The normal weekly cycle is:

1. `source-maintenance-report` runs weekly and produces source verification, quality queue, observation ledger, latest health, and public source-health snapshot artifacts.
2. `source-refinement-scan` runs weekly after source maintenance and compares the latest two successful source-maintenance runs.
3. Maintainers inspect confirmed P0 evidence and the Layer 2C source quality queue.
4. Confirmed P0 repair is batched into small human-reviewed plans.
5. Catalog expansion pauses when source-health debt is high enough that new growth would hide repair work.
6. Generated stale source repair PRs are cleaned up after 30 days if they remain unreviewed and stale.

Healthy operation means the weekly maintenance artifact exists, confirmed P0 debt is understood, quality-risk sources are queued for review, release candidates have source-health readiness artifacts, and the public site can display the latest source-health snapshot when available.

## Automatic Operations

These workflows run without maintainer input:

- `source-maintenance-report`: builds source-health, network verification, source quality, observation, latest-health, public snapshot, discovery, promotion, and cleanup proposal artifacts.
- `source-refinement-scan`: compares the latest two successful source-maintenance reports and emits confirmed P0 candidates, raw repair evidence, and skipped repair-plan validation when no plan is provided.
- `source-repair-pr-cleanup`: closes stale generated repair PRs older than 30 days when they are generated repair PRs and have no detected human activity.
- `agent-automerge`: enforces machine-canonical source preflight and the strict Layer 2B P0 repair lane when the required labels and evidence are present.
- `site-pages`: consumes the latest public source-health snapshot artifact when available, then builds and deploys the public site.

Automatic workflows do not discover replacements, author repair plans, mutate catalog source records, or create source repair PRs without committed human-reviewed validation reports.

## Manual Review Operations

Maintainers still review:

- Confirmed P0 repair evidence.
- Maintainer-authored P0 repair plans under `maintenance/reviewed/`.
- Validation reports committed under `maintenance/reviewed/`.
- Generated `Catalog: repair*` PRs before merge unless the strict Layer 2B automerge lane is intentionally used.
- Layer 2C quality queue items.
- Ambiguous access statuses such as bot protection, forbidden access, gated login, or rate limiting.
- Entity, category, jurisdiction, and source-type correctness.

Quality refinement is human reviewed only. Do not treat quality fixes as confirmed-dead P0 repairs.

## Confirmed P0 Repair Process

Use this process for sources repeatedly confirmed as hard-dead with exact `not_found` to `not_found` or `gone` to `gone` evidence:

1. Inspect `confirmed-p0-repair-candidates.json` and `source-repair-evidence.json`.
2. Select a small batch, normally 5-10 records.
3. Manually identify replacement URLs only when they are public, reachable, same `source_type`, strong semantic matches, and vendor-controlled or clearly approved.
4. Commit a reviewed repair plan under `maintenance/reviewed/`.
5. Run source-refinement validation with the committed plan path.
6. Commit the resulting validation report under `maintenance/reviewed/`.
7. Run `source-repair-pr` with the committed validation report.
8. Review the generated `Catalog: repair*` PR and confirm that changed files are bounded.

Manual repair batch policy: 5-10 records per batch. Large batches are harder to review and should be split.

## Layer 2B Label Discipline

Strict P0 repair automerge is optional and narrow. It requires both labels:

```text
source-refinement
automerge:p0-source-repair
```

The strict lane independently checks committed validation and evidence reports, changed paths, maximum repair count, source type preservation, and rejected self-certifying fields such as `eligible`, `eligible_for_automerge`, or `tool_recommendation`.

Strict P0 automerge batch policy: max 10 records per PR.

Never apply Layer 2B automerge labels to:

- Layer 2C quality fixes.
- Access ambiguity.
- Possible mismatch.
- Entity corrections.
- Source type changes.
- Human-authored cleanup PRs.
- Catalog completeness or confidence label work.

## Layer 2C Quality Queue Process

Layer 2C covers reachable but poor-quality source records:

- `homepage_or_generic_redirect`
- `possible_mismatch`
- `suspect_inferred_url`

These items are not confirmed-dead P0 repairs. Reviewers should verify semantic match, source type, entity, and authority before changing anything. Quality refinement is human reviewed only and must not be marked automerge-eligible.

## Release Health Gate

`release-candidate` builds release source-health readiness from source-maintenance artifacts. The policy is:

- Confirmed P0 blocks release when enforcement is active.
- Missing or invalid source-health artifacts block release when enforcement is active.
- Ambiguous access and quality statuses warn only.
- Readiness artifacts are uploaded so maintainers can see why a release candidate was blocked or warned.

After WP-L3D, `release-candidate` defaults to `enforce`. `report_only` remains a diagnostic escape hatch for observing readiness without blocking.

## Site Snapshot Behavior

The public site consumes `public/source-health-snapshot.json` from the latest source-maintenance artifact when available.

Site labels are snapshot based:

- `healthy`: Verified
- `warning`: Needs review
- `unavailable`: Unavailable
- `ambiguous`: Access ambiguous
- Missing health row: Not yet verified

Source health is a maintenance snapshot and may change. It does not imply catalog completeness, legal approval, compliance, procurement fitness, security assurance, or vendor-risk suitability.

## Stale Repair PR Cleanup

`source-repair-pr-cleanup` scans open PRs and closes only stale generated source repair PRs that match all of these conditions:

- Title starts with `Catalog: repair`.
- Head branch starts with `agent-source-repair`.
- Author is `github-actions[bot]` when available.
- PR is older than 30 days.
- No recent human comments or reviews are detected.

It does not close human-authored PRs, non-repair PRs, fresh PRs, or PRs with detected human review activity.

## Emergency Procedures

If source trust automation behaves unexpectedly:

1. Pause new catalog expansion until the source-health state is understood.
2. Use `source_health_policy: report_only` for diagnostic release-candidate runs when investigating release gate failures.
3. Remove Layer 2B automerge labels from questionable repair PRs.
4. Close or supersede generated repair PRs whose evidence has gone stale.
5. Re-run `source-maintenance-report` before authoring new repair plans.
6. Prefer smaller repair batches and explicit human review when evidence is ambiguous.
7. Do not bypass source preflight for machine-canonical PRs that change source records.

Do not use emergency handling to add automerge to quality refinement, entity correction, source type changes, or unverified replacement URLs.
