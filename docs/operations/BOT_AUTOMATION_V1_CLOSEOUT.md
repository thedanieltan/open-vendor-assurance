# OpenVA Bot Automation v1 Closeout

WP28 closes out Bot Automation v1, the bot governance arc delivered as WP9 through WP27.

This record is factual. It grants no new authority and changes no contracts, workflows, or schemas. It exists so that future maintainers can answer one question without archaeology: which bot capabilities are live, which are not, and where the boundaries are written down.

## Completion Status

Bot Automation v1 is complete. The bot operating model defined in `docs/operations/BOT_OPERATING_MODEL.md` is active.

The first and only live chat-ops mutation surface is `/openva hold` and `/openva unhold`, documented in `docs/operations/BOT_CHATOPS_EXECUTION.md`.

## Work Package Record

| WP | Deliverable | Record |
|---|---|---|
| WP9 | Bot operating model: authority lanes, command vocabulary, failure taxonomy, retirement rules, machine-readable contracts | `docs/operations/BOT_OPERATING_MODEL.md`, `docs/operations/contracts/` |
| WP10 | Deterministic local dashboard render | `docs/operations/BOT_DASHBOARD.md` |
| WP11 | Queue policy enforcer (local, report-only) | `docs/operations/BOT_QUEUE_ENFORCER.md` |
| WP12 | Failure router classifier (local, report-only) | `docs/operations/BOT_FAILURE_ROUTER.md` |
| WP13 | Chat-ops command surface and parser | `docs/operations/BOT_CHATOPS.md` |
| WP15 | Dashboard issue sync substrate | `docs/operations/BOT_DASHBOARD_ISSUE_SYNC.md` |
| WP16 | Bot observability scorecard | `docs/operations/BOT_OBSERVABILITY.md` |
| WP17 | Bot ops smoke harness | `docs/operations/BOT_OPS_SMOKE_HARNESS.md` |
| WP18 | Dashboard issue sync workflow (dry-run default) | `docs/operations/BOT_DASHBOARD_ISSUE_SYNC.md` |
| WP19 | Queue enforcer integration into PR workflows | `docs/operations/BOT_QUEUE_ENFORCER.md` |
| WP20 | Failure router integration into workflow failure paths | `docs/operations/BOT_FAILURE_ROUTER.md` |
| WP21 | Chat-ops local execution (`/openva explain-strict-growth`, hold, unhold as local-audit-only) | `docs/operations/BOT_CHATOPS.md` |
| WP22 | Workflow consolidation audit; quarantine of `source-refinement-queue.yml` | `docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md`, `docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md` |
| WP23 | Bot ops calibration decision framework | `docs/operations/BOT_OPS_CALIBRATION.md` |
| WP24 | Dashboard signal quality layer | `docs/operations/BOT_DASHBOARD_SIGNAL_QUALITY.md` |
| WP26 | Quarantine of `observe-report.yml` | `docs/operations/WORKFLOW_CONSOLIDATION_AUDIT.md`, `docs/operations/WORKFLOW_RETIREMENT_EVIDENCE.md` |
| WP27 | Live hold/unhold chat-ops execution | `docs/operations/BOT_CHATOPS_EXECUTION.md`, `.github/workflows/bot-chatops.yml` |

## WP27 Post-Merge Smoke Evidence

- WP27 merged to `main` via PR #345 (`agent/wp27-live-hold-readiness-smoke-2`, merge commit `c9b7ed7`).
- Post-merge live smoke ran on issue #346:
  - `/openva hold` added the `openva-hold` label and posted an audit comment.
  - `/openva unhold` removed the `openva-hold` label and posted an audit comment.
- Issue #346 was closed as completed with no labels remaining.

Live hold/unhold is therefore active and smoke-tested, not experimental.

## Authority Boundary

The live authority boundary at closeout is:

- `/openva hold` and `/openva unhold` are live. They may add or remove only the `openva-hold` label, only on the issue or pull request where the command comment was posted. No target, label, or scope arguments are accepted.
- Live execution is gated to comment actors GitHub reports as `OWNER`, `MEMBER`, or `COLLABORATOR`.
- The live surface is `.github/workflows/bot-chatops.yml`, operating under the `bot_chatops_hold` lane in `docs/operations/contracts/bot-authority.yaml` (`max_open_prs: 0`, `issue_comment_only`, label actions limited to add/remove of `openva-hold`).
- All other `/openva` commands remain report-only, local-audit-only, or denied. `/openva explain-strict-growth` is local-audit-only. `/openva retry-source-preflight`, `/openva defer-candidate`, `/openva promote-reviewed-plan`, `/openva quarantine-source`, and `/openva recheck-final-url` are not executable.
- No bot lane may write catalog truth outside the existing review-gated PR paths. Undeclared lanes and undeclared write paths remain deny-by-default.

Any expansion of this boundary requires a new work package with its own contract changes, tests, and smoke evidence. This closeout does not pre-authorize any expansion.

## Maintainer Note

`/openva hold` and `/openva unhold` are live, constrained to the `openva-hold` label, and smoke-tested. If a future reader is unsure whether live hold/unhold is experimental: it is not. The rollback options remain documented in `docs/operations/BOT_CHATOPS_EXECUTION.md`.
