# OpenVA Bot Dashboard Issue Sync

WP15 defined the OpenVA bot dashboard issue sync substrate. WP18 adds a conservative GitHub Actions workflow that renders the WP10 dashboard and runs issue sync in dry-run/report-only mode by default.

This document is separate from `docs/operations/BOT_DASHBOARD.md` because rendering and publication have different safety boundaries. The renderer creates local Markdown from contracts and optional artifacts. The issue-sync tool decides whether one persistent GitHub issue would be created or updated.

The machine-readable contract is `docs/operations/contracts/bot-dashboard-issue.yaml`.

## Purpose

OpenVA needs one durable bot dashboard issue comparable to a dependency dashboard. The issue should consolidate bot posture, strict-growth ready candidates, deferred candidates, review-required candidates, source-health failures, redirect deferrals, coverage gaps, stale backlog items, recent run state, and next safe action.

The sync tool avoids scattered bot status issues and comments. It targets one exact issue title and refuses to proceed when multiple open matching issues exist.

## Persistent Issue Model

The contract declares:

- dashboard source: `maintenance/bot-dashboard.md`
- issue title: `OpenVA Bot Dashboard`
- issue labels: `bot-dashboard`, `operations`
- duplicate policy: `fail_if_multiple_open_matching_issues`
- create-if-missing behavior
- update-if-present behavior
- required token permissions
- forbidden side effects

The issue body is the generated dashboard Markdown. The sync report includes a stable body hash so maintainers can compare dry-run output before enabling a write.

## Dry-Run Behavior

Dry-run is the default. In dry-run mode, the tool reads the dashboard, computes the body hash, evaluates the target issue decision, and writes a local report. It does not create issues, update issues, label PRs, dispatch workflows, or mutate catalog data.

When a token or injected client is unavailable, dry-run may report that open issue discovery was not checked locally. That is still safe because no GitHub state changes. A real update must first resolve duplicates against the GitHub issue list.

The workflow default is also dry-run. Manual runs and scheduled runs render `maintenance/bot-dashboard.md`, run `tools.openva.bot_dashboard_issue sync`, and upload the generated dashboard plus sync report artifacts. Scheduled runs always behave as dry-run/report-only.

## Report-Only Behavior

Report-only is also the default. Report-only mode blocks issue creation or update even when dry-run is disabled. Live issue writes require a manual workflow run with `dry_run: "false"`, which passes both `--apply` and `--allow-issue-update` to the sync tool.

This keeps WP18 conservative: scheduled automation remains dry-run/report-only, while a maintainer can explicitly request one real issue create/update after reviewing the same workflow path.

## Duplicate Issue Safety

The sync target is exact-title based. If no explicit issue number is provided, the tool searches open issues with the configured labels and filters to the exact title.

Decision rules:

- zero matching open issues: create-if-missing path
- one matching open issue: update-if-present path
- multiple matching open issues: denied
- explicit issue number: update only that issue number

The tool must not update arbitrary issues. Explicit issue numbers are recorded in the report and remain subject to dry-run/report-only gates.

## Permission Posture

The minimum live permissions are:

- `contents: read`
- `issues: write`

Forbidden side effects:

- catalog mutation
- workflow dispatch
- pull request mutation
- automerge mutation
- queue enforcement
- slash-command execution

The sync tool does not request pull request permissions and does not call workflow dispatch endpoints.

## Workflow Integration

WP18 adds `.github/workflows/bot-dashboard-issue.yml`.

The workflow:

- supports `workflow_dispatch`
- runs on a conservative weekly schedule
- uses `contents: read` and `issues: write`
- renders the WP10 dashboard first
- runs dashboard issue sync in dry-run/report-only mode unless `dry_run: "false"`
- accepts optional `dashboard_issue_number` for an explicit target
- uploads `openva-bot-dashboard` and `openva-bot-dashboard-issue-sync-report` artifacts
- has no PR write permission
- does not dispatch workflows, label PRs, mutate catalog data, or change automerge state

To run it manually, choose **Run workflow**, keep `dry_run` as `"true"` for a report-only preview, and optionally provide `dashboard_issue_number` when maintainers have already identified the durable dashboard issue. Use `dry_run: "false"` only after reviewing the dry-run artifact and confirming duplicate issue status is safe.

## Rollback And Disable Plan

Rollback is simple because the sync target is one issue:

1. Leave the issue open and stop running issue sync.
2. Re-run the tool in dry-run mode to compare desired content without mutation.
3. If duplicate issues exist, close or manually consolidate them before enabling writes.
4. If the dashboard source is stale or missing, regenerate `maintenance/bot-dashboard.md` locally before sync.

If the bot dashboard issue ever becomes noisy, maintainers can keep the local dashboard renderer and disable issue sync without affecting catalog growth, promotion actions, source repair, reviewed evidence, strict-growth, or controlled promotion.
