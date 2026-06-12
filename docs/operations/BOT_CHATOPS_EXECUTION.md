# OpenVA Bot Chat-Ops Execution

WP27 enables the first live chat-ops mutation surface for OpenVA: `/openva hold` and `/openva unhold` may add or remove only the `openva-hold` label on the current issue or pull request.

This is not full chat-ops. It does not dispatch workflows, open PRs, close PRs, merge PRs, mutate catalog data, change automerge policy, retire workflows, or allow arbitrary labels or targets.

## Enabled Commands

| Command | Execution | Side effect |
|---|---|---|
| `/openva explain-strict-growth` | Local/audit enabled | Generates deterministic strict-growth explanation markdown and an execution audit report. |
| `/openva hold` | Live label mutation | Adds only the `openva-hold` label to the current issue or pull request. |
| `/openva unhold` | Live label mutation | Removes only the `openva-hold` label from the current issue or pull request. |

## Disabled Commands

The following commands remain report-only or denied by the execution layer:

- `/openva retry-source-preflight`
- `/openva defer-candidate`
- `/openva promote-reviewed-plan`
- `/openva quarantine-source`
- `/openva recheck-final-url`

These commands require stronger runtime authority, fresher queue state, and more specific failure recovery contracts before they can safely mutate anything.

## Actor Authorization

Live hold/unhold execution is allowed only when GitHub reports the comment actor as one of:

- `OWNER`
- `MEMBER`
- `COLLABORATOR`

The local executor still uses the simplified `maintainer` actor role for deterministic tests and local audit reports. The live workflow uses GitHub `author_association` from the `issue_comment` event.

## Live Workflow Boundary

The live workflow is `.github/workflows/bot-chatops.yml`.

It is triggered only by:

```yaml
on:
  issue_comment:
    types: [created]
```

It requests only:

```yaml
permissions:
  contents: read
  issues: write
  pull-requests: read
```

It may mutate only one label:

```text
openva-hold
```

It must not write branches, open PRs, merge PRs, dispatch workflows, mutate catalog data, or change automerge state.

## Audit Trail

Every accepted or denied live command posts an audit comment with:

- status
- raw command
- actor
- actor association
- target issue or pull request number
- summary
- reason or mutation performed

The local CLI can still write JSON and markdown reports:

```bash
python -m tools.openva.bot_chatops_execute execute \
  --comment-file comment.txt \
  --actor-role maintainer \
  --out maintenance/bot-chatops-execution-report.json \
  --out-md maintenance/bot-chatops-execution-report.md
```

## Hold And Unhold Semantics

`/openva hold` and `/openva unhold` name only one allowed label: `openva-hold`.

The following remain denied:

- `/openva hold #123`
- `/openva unhold #123`
- `/openva hold all`
- `/openva hold urgent`
- multiple `/openva` commands in one comment
- non-maintainer actors

The command body cannot select a label or another target.

## Queue And Failure Router Integration

Hold/unhold now use the dedicated `bot_chatops_hold` authority and queue lane. This lane is not PR-based:

- `max_open_prs: 0`
- `schedule_window: issue_comment_only`
- `allowed_label: openva-hold`
- `allowed_actions: [add, remove]`

The local executor remains audit-only and does not call GitHub APIs. Live mutation is confined to the GitHub workflow.

## Failure Modes

Common failure outcomes include:

- non-maintainer actor -> denied
- unknown command -> denied
- multiple commands in one comment -> denied
- high-risk command -> report-only, not executed
- target or label argument supplied -> denied
- GitHub label API failure -> workflow failure requiring maintainer review

## Post-Merge Smoke Evidence

WP28 records that live hold/unhold passed post-merge smoke after PR #345 merged to `main`:

- On issue #346, `/openva hold` added the `openva-hold` label and posted an audit comment.
- On the same issue, `/openva unhold` removed the `openva-hold` label and posted an audit comment.
- Issue #346 was closed as completed with no labels remaining.

Live hold/unhold is active, not experimental. The closeout record for Bot Automation v1 is `docs/operations/BOT_AUTOMATION_V1_CLOSEOUT.md`.

## Rollback And Disable Plan

Rollback options, from least to most disruptive:

1. Remove or disable `.github/workflows/bot-chatops.yml`.
2. Remove the `issue_comment` trigger.
3. Set `/openva hold` and `/openva unhold` back to `mode: local_audit_only` and `may_mutate_labels: false`.
4. Remove the `bot_chatops_hold` authority and queue lane after no workflow references it.
