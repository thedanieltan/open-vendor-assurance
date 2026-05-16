# OpenVA Maintenance Operator Runbook

This runbook explains how maintainers operate reviewed OpenVA catalog maintenance.

## Maintenance loop overview

Scheduled/report-only workflows:

- source verification
- source discovery
- promotion planning
- cleanup proposal issue/artifacts

Reviewed cleanup path:

1. add a reviewed promotion plan under `maintenance/reviewed/`.
2. run `catalog-maintenance-pr` with that reviewed plan.
3. review the generated Catalog PR.
4. merge the generated Catalog PR after validation.
5. treat repeat runs with no changes as successful no-ops.

Candidate sources are not canonical sources. Unavailable-source records are reviewed absence or omission records. Promotion plans are reviewable plans, not truth. `catalog-maintenance-pr` applies only reviewed plans.

## Creating a reviewed cleanup plan

Reviewed cleanup plans live under:

```text
maintenance/reviewed/*.json
```

Example:

```text
maintenance/reviewed/promotion-plan-cleanup-2.json
```

Required posture:

```text
network_fetch_performed: false
writes_repository_state: false
writes_canonical_sources: false
non_advisory: true
```

Allowed cleanup actions:

```text
cleanup_source_for_review
retire_or_replace_source_for_review
```

## Running `catalog-maintenance-pr`

Example inputs:

```text
promotion_plan_path: maintenance/reviewed/promotion-plan-cleanup-2.json
pr_branch: agent-catalog-maintenance-cleanup-N
pr_title: Catalog: apply reviewed source maintenance cleanup
```

## Success

Success means the workflow creates a Catalog PR, the PR validates, and a maintainer reviews and merges it.

## No-op rerun

If the reviewed plan has already been applied, the workflow may log:

```text
No catalog maintenance changes produced.
```

Expected result: green workflow and no PR created.

## PR creation failure

Check this repo setting:

```text
Settings -> Actions -> General -> Workflow permissions
Read and write permissions
Allow GitHub Actions to create and approve pull requests
```

If a branch is pushed but no PR is created, manually open a PR from the `agent-catalog-maintenance-cleanup-*` branch.

## Guardrails

- non-advisory catalog maintenance only.
- no vendor recommendations.
- no compliance or approval conclusion about a vendor.
- no raw vendor document mirroring.
- no raw vendor document mirrored into the repository.
- no gated, private, customer-only, or authenticated-only sources.
- no candidate auto-promotion.
