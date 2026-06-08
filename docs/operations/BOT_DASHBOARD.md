# OpenVA Bot Dashboard

The OpenVA Bot Dashboard is the durable local control surface for bot posture, queue state, backlog aging, and next safe actions. It sits under the WP9 Bot Operating Model and turns the WP9 contracts into an operator-readable dashboard.

WP10 does not create or update a GitHub issue. It defines the dashboard contract and provides a deterministic local renderer. A later work package may copy the generated dashboard into a durable GitHub control issue.

WP24 adds a signal-quality layer so maintainers can distinguish blocking issues from action-required signals, watch items, informational telemetry, and missing optional local artifacts.

## Purpose

The dashboard gives maintainers one place to inspect:

- Current Bot Posture
- Signal Quality Summary
- Pause Switch Status Model
- Strict-Growth Ready Candidates
- Deferred Candidates
- Review-Required Candidates
- Source-Health Failures
- Redirect Deferrals
- Coverage Gaps
- Stale Backlog Items
- Last Successful Catalog-Growth Run
- Last Failed Run
- Next Safe Action
- Queue Policy Summary
- Authority Summary By Lane
- Failure Taxonomy Summary
- Stale Evidence Thresholds
- Missing Local Artifacts
- Operator Checklist

The dashboard is advisory. It does not mutate catalog truth, enforce queue limits, execute slash commands, create PRs, label PRs, merge PRs, or run workflows.

## Generated Versus Reviewed

Generated content comes from local contracts and optional local artifacts:

- `docs/operations/contracts/bot-authority.yaml`
- `docs/operations/contracts/bot-failure-taxonomy.yaml`
- `docs/operations/contracts/bot-queue-policy.yaml`
- `docs/operations/contracts/bot-dashboard.yaml`
- local catalog-growth, source-health, and coverage artifacts when present

Manual review is still required for any action that would change catalog truth, source repair state, promotion actions, PR labels, auto-merge state, or workflow posture. Discovery may propose; controlled promotion writes.

## Signal Quality Summary

The `Signal Quality Summary` section ranks the most important dashboard signals before the detailed operational sections.

Signal classes are defined in `docs/operations/contracts/bot-dashboard.yaml`:

- `blocking`
- `action_required`
- `watch`
- `informational`
- `missing_optional_input`
- `unknown`

Blocking signals appear before informational telemetry. Missing optional artifacts are explicitly separated from actionable failures so the dashboard does not create false critical posture when local generated reports are absent.

## Missing Artifact Fallback

The renderer must tolerate missing optional artifacts. When an artifact is absent, the dashboard renders a `Missing Local Artifacts` section and keeps the affected operational section in an advisory fallback state.

Missing local artifacts mean "not available in this checkout"; they do not imply workflow failure. Operators should use the next safe action and stale evidence thresholds before deciding whether to refresh evidence.

## Stale Artifact Behavior

The dashboard contract declares stale thresholds for artifacts that carry evidence. Stale evidence should be invalidated before strict-growth promotion, source repair, or merge decisions.

The local renderer is deterministic by default. It reports thresholds and artifact timestamps when available. A future issue-update workflow may evaluate freshness against a run timestamp before publishing a dashboard comment.

## Future GitHub Issue Path

The intended future control issue title is declared in `docs/operations/contracts/bot-dashboard.yaml`. WP10 does not create or update that issue.

A later implementation may:

- render `maintenance/bot-dashboard.md`
- compare it with the current dashboard issue body
- update the issue only when content changes
- include links to workflow runs and artifacts
- preserve maintainer comments as the reviewed decision trail

That future implementation must remain under WP9 authority, queue, failure taxonomy, and permission contracts.

## Operator Use

Operators should read the dashboard in this order:

1. Confirm the current bot posture and pause switch model.
2. Read the Signal Quality Summary.
3. Check strict-growth ready candidates and review-required candidates.
4. Check source-health failures, redirect deferrals, coverage gaps, and stale backlog items.
5. Confirm queue policy limits and stale evidence thresholds.
6. Use the next safe action only if it is consistent with bot authority and reviewed evidence.
7. Avoid any catalog mutation from report-only lanes or missing evidence.
