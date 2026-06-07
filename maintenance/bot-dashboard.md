# OpenVA Bot Dashboard

Generated from local WP9/WP10 contracts and optional local artifacts. This dashboard is advisory and does not update GitHub issues.

## Current Bot Posture

- Undeclared lanes denied: `True`
- Undeclared write paths denied: `True`
- Report-only lanes may write catalog truth: `False`
- Discovery lanes may write catalog truth: `False`
- Dashboard issue update enabled: `False`

## Pause Switch Status Model

- Global pause switch label: `openva-bot-paused`
- Local renderer status: `not_evaluated_without_github_issue_state`
- If the pause switch is active, all write-capable bot actions should stop before branch, PR, label, or merge changes.

## Strict-Growth Ready Candidates

- Eligibility strict-ready candidates: `5`
- Reviewed promotion actions in local plan: `8`
- Discovery queue cohorts: `16`
- Eligibility classifications: `{"reject_existing_vendor": 9, "reject_no_public_source": 125, "reject_source_health_failure": 2, "reject_weak_semantic_match": 1, "review_required": 1, "strict_promote_ready": 5}`

## Deferred Candidates

- Deferred candidates detected locally: `0`
- Deferred state is advisory until dashboard issue automation is implemented.

## Review-Required Candidates

- Review-required candidates/actions detected locally: `1`
- Manual review remains required before source repair or controlled promotion.

## Source-Health Failures

- Source-health failure rows detected locally: `0`
- Eligibility source-related failures: `127`

## Redirect Deferrals

- Redirect deferrals detected in local promotion plan: `6`
- Redirect ambiguity should use `redirect_canonicalization_failure` until reviewed evidence clears it.

## Coverage Gaps

- `vendors_below_three_core_artifacts`: `52`
- `vendors_missing_dpa`: `64`
- `vendors_missing_subprocessors_list`: `58`
- `vendors_with_single_artifact`: `23`

## Stale Backlog Items

- Stale backlog evaluation is policy-defined and should invalidate evidence before write recommendations.
- Strict-growth stale evidence threshold hours: `4`

## Last Successful Catalog-Growth Run

- Last successful local catalog-growth artifact timestamp: `2026-06-06T11:13:04Z`

## Last Failed Run

- No failed local artifact parse was detected.

## Next Safe Action

- Review the strict-growth promotion plan, confirm stale evidence thresholds, and use controlled promotion only if fewer than 1 catalog-growth PRs are open.

## Queue Policy Summary

- Max open catalog-growth PRs: `1`
- Max open source-repair PRs: `1`
- Max bot PRs per day: `3`
- Max bot PRs per week: `10`
- Cooldown after failure hours: `24`

| Lane | Max open PRs | Max actions per PR | Schedule | Source-host rate limit | Vendor-domain concurrency |
|---|---:|---:|---|---|---:|
| `source_repair` | 1 | 10 | weekly_or_manual | conservative | 1 |
| `catalog_growth_promotion` | 1 | 10 | weekly_or_manual | conservative | 1 |
| `support_agent_pr` | 2 | 5 | manual_only | conservative | 1 |

## Authority Summary By Lane

| Lane | Status | Workflows | Branch writes | Opens PRs | Merges PRs | Catalog truth | Deny by default |
|---|---|---:|---|---|---|---|---|
| `pr_safety` | active | 4 | False | False | True | False | True |
| `source_maintenance_report` | active | 2 | False | False | False | False | True |
| `source_repair` | active | 2 | True | True | False | True | True |
| `catalog_quality` | active | 1 | False | False | False | False | True |
| `catalog_growth_discovery` | active | 1 | False | False | False | False | True |
| `catalog_growth_promotion` | active | 1 | True | True | False | True | True |
| `publication` | active | 4 | False | False | False | False | True |
| `support_agent_pr` | active | 3 | True | True | False | True | True |
| `legacy_report` | shadow_report_only | 3 | False | False | False | False | True |

## Failure Taxonomy Summary

| Code | Retry | Escalation | Defer | Stop lane |
|---|---|---|---|---|
| `source_preflight_failure` | True | source-maintainer | True | False |
| `redirect_canonicalization_failure` | True | source-maintainer | True | False |
| `duplicate_url_failure` | False | catalog-maintainer | True | False |
| `terminology_contract_failure` | True | operations-maintainer | False | True |
| `schema_validation_failure` | True | operations-maintainer | False | True |
| `generated_drift_failure` | True | operations-maintainer | False | True |
| `workflow_input_compatibility_failure` | True | workflow-maintainer | False | True |
| `automerge_lane_mismatch` | True | maintainer | False | True |
| `external_fetch_instability` | True | source-maintainer | True | False |
| `stale_evidence_failure` | True | maintainer | True | False |
| `permission_policy_denial` | False | maintainer | False | True |

## Stale Evidence Thresholds

- `deterministic_outputs`: `24` hours
- `source_repair`: `24` hours
- `strict_growth`: `4` hours
- `catalog_growth_discovery_queue`: `168` hours
- `strict_growth_eligibility_report`: `4` hours
- `strict_growth_promotion_plan`: `4` hours
- `strict_growth_shortlist`: `4` hours
- `source_health_snapshot`: `24` hours
- `source_health_report`: `24` hours
- `coverage_audit_report`: `24` hours
- `catalog_completeness_report`: `24` hours
- `entity_review_queue`: `24` hours
- `field_provenance_coverage`: `24` hours

## Missing Local Artifacts

| Artifact | Path | Section |
|---|---|---|
| `source_health_snapshot` | `public/source-health-snapshot.json` | source_health_failures |
| `source_health_report` | `reports/source-health-report.json` | source_health_failures |
| `catalog_completeness_report` | `reports/catalog-completeness-report.json` | coverage_gaps |
| `entity_review_queue` | `reports/entity-review-queue.json` | review_required_candidates |
| `field_provenance_coverage` | `reports/field-provenance-coverage.json` | coverage_gaps |

## Operator Checklist

- Confirm the pause switch is not active before any write-capable action.
- Treat missing local artifacts as unavailable evidence, not as successful runs.
- Refresh stale strict-growth evidence before controlled promotion.
- Keep discovery and report-only lanes from mutating catalog truth.
- Use reviewed evidence for source repair and controlled promotion.
- Do not create or update a GitHub issue from this local renderer.
