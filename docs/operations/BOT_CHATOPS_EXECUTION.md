# OpenVA Bot Chat-Ops Execution

WP21 enables a narrow execution layer for low-risk OpenVA chat-ops commands. It builds on the WP13 parser, WP11 queue policy, WP12 failure routing, and WP9 bot authority contracts.

This is not full chat-ops. It does not listen to comments by itself, dispatch workflows, open PRs, close PRs, merge PRs, mutate catalog data, change automerge policy, or retire workflows.

## Enabled Commands

| Command | Execution | Side effect |
|---|---|---|
| `/openva explain-strict-growth` | Enabled | Generates deterministic strict-growth explanation markdown and an execution audit report. |
| `/openva hold` | Enabled | Generates a hold-state audit report for the `openva-hold` label; label mutation is not enabled in WP21. |
| `/openva unhold` | Enabled | Generates an unhold-state audit report for the `openva-hold` label; label mutation is not enabled in WP21. |

## Disabled Commands

The following commands remain report-only or denied by the execution layer:

- `/openva retry-source-preflight`
- `/openva defer-candidate`
- `/openva promote-reviewed-plan`
- `/openva quarantine-source`
- `/openva recheck-final-url`

These commands require stronger runtime authority, fresher queue state, and more specific failure recovery contracts before they can safely mutate anything.

## Actor Authorization

Execution requires the actor role `maintainer`. Non-maintainer commands are denied even when the command is otherwise supported.

The local executor does not discover actor roles. A future comment-listener workflow must supply the role from a safe authorization source.

## Audit Trail

Every execution report includes:

- raw command input
- parsed command decision
- authorization decision
- queue decision, when required
- failure routing report, when denied or blocked
- execution report
- next safe action

The CLI can write JSON and markdown reports:

```bash
python -m tools.openva.bot_chatops_execute execute \
  --comment-file comment.txt \
  --actor-role maintainer \
  --out maintenance/bot-chatops-execution-report.json \
  --out-md maintenance/bot-chatops-execution-report.md
```

## Hold And Unhold Semantics

`/openva hold` and `/openva unhold` are intentionally conservative in WP21. They name only one allowed label: `openva-hold`.

The executor reports what would happen to that label on the current comment thread, but it does not apply or remove labels. A future workflow may enable live label mutation only if the contract continues to restrict the operation to:

- `openva-hold`
- the issue or PR where the command appears
- authorized maintainers
- no arbitrary issue numbers
- no catalog data
- no workflow files

## Queue And Failure Router Integration

`/openva hold` and `/openva unhold` require queue state because they are support-lane controls. If queue state is missing or the queue decision is not `allow`, execution is denied and the failure router classifies the blocked command.

`/openva explain-strict-growth` does not require a queue check because it is informational only.

## Failure Modes

Common failure outcomes include:

- non-maintainer actor -> denied
- unknown command -> denied
- multiple commands in one comment -> denied
- high-risk command -> report-only, not executed
- missing queue state for hold/unhold -> denied
- stale or paused queue state -> denied and routed through the failure router

## Rollback And Disable Plan

The safest rollback is to set the three executable commands in `docs/operations/contracts/bot-chatops.yaml` back to:

```yaml
status: planned_report_only
executable: false
report_only: true
side_effect_class: report_only
```

If a future workflow is added, disabling that workflow or removing its `issue_comment` trigger must stop live chat-ops ingestion without changing the local parser.
