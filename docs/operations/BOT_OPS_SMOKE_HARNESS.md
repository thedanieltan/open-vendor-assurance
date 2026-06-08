# OpenVA Bot Ops Smoke Harness

WP17 defines a local end-to-end smoke harness for the OpenVA bot operating system. The harness proves that the report-only bot stack can run together without GitHub mutation, workflow dispatch, PR mutation, issue mutation, or catalog data changes.

## Purpose

The bot operating system now has contracts and tools for dashboard rendering, queue decisions, failure routing, chat-ops parsing, workflow retirement planning, dashboard issue sync, and observability. The smoke harness exercises those pieces in one deterministic local sequence so maintainers can detect contract drift before enabling stronger bot capabilities.

This harness is a pre-activation check. It is not a production workflow and does not authorize new bot behavior.

## Local-Only Guarantee

The harness imports local modules and reads local contracts. It does not call GitHub APIs, invoke `gh`, use network clients, dispatch workflows, create issues, update issues, label PRs, merge PRs, or change workflow files.

Dashboard issue sync is invoked only in dry-run and report-only mode. It records a dry-run decision and does not create or update the durable dashboard issue.

## Report-Only Guarantee

The smoke sequence writes only its requested output reports:

- `maintenance/bot-ops-smoke-report.json`
- `maintenance/bot-ops-smoke-report.md`

Generated smoke reports are optional local outputs. The harness does not mutate catalog data, generated catalog indexes, workflow definitions, PR state, issue state, dashboard issue state, queue state, or chat-ops command state.

## Sequence

The smoke harness runs:

1. Validate required bot operating contracts parse and exist.
2. Render the bot dashboard in memory.
3. Evaluate a clean queue sample that should allow.
4. Evaluate a blocked queue sample that should defer.
5. Route one explicit failure through the failure taxonomy.
6. Parse one allowed report-only chat-ops command.
7. Parse one denied chat-ops command.
8. Dry-run dashboard issue sync.
9. Generate the workflow retirement report in memory.
10. Generate the observability scorecard in memory.
11. Summarize the next safe action.

## Inputs

Inputs are the local bot operating contracts and existing local reports when present:

- `docs/operations/contracts/bot-authority.yaml`
- `docs/operations/contracts/bot-queue-policy.yaml`
- `docs/operations/contracts/bot-failure-taxonomy.yaml`
- `docs/operations/contracts/bot-dashboard.yaml`
- `docs/operations/contracts/bot-chatops.yaml`
- `docs/operations/contracts/bot-dashboard-issue.yaml`
- `docs/operations/contracts/workflow-retirement.yaml`
- `docs/operations/contracts/bot-observability.yaml`
- `docs/operations/contracts/workflow-inventory.yaml`
- optional local maintenance reports

Missing optional observability inputs are reported by the observability scorecard and do not fail the smoke harness.

## Outputs

The JSON report includes one subsystem result for:

- contracts
- dashboard
- queue
- failure router
- chat-ops
- dashboard issue sync
- workflow retirement
- observability

The Markdown report mirrors the same subsystem summary and includes the next safe action.

## Expected Failure Modes

The harness should fail clearly when:

- a required contract file is missing
- a required YAML contract does not parse
- the clean queue sample does not allow
- the blocked queue sample does not defer or deny
- the explicit failure does not route to the expected taxonomy code
- the allowed chat-ops command is not accepted as report-only
- the denied chat-ops command is not denied
- workflow retirement validation reports contract errors
- dashboard issue sync is not dry-run/report-only

## Maintainer Use

Run the harness before enabling new bot capabilities, widening bot permissions, adding dashboard issue automation, changing queue policy, changing chat-ops behavior, or preparing destructive workflow retirement.

The harness should pass before a future PR enables any non-report-only bot behavior.

## Workflow Retirement Support

Destructive workflow retirement must remain separate from WP17. The harness supports future retirement by proving that workflow classification, dashboard, queue, failure routing, chat-ops, dashboard issue sync, and observability can run together locally before any workflow is disabled, renamed, or deleted.
