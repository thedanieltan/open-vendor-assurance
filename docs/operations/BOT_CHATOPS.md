# OpenVA Bot Chat-Ops

OpenVA chat-ops gives maintainers a common command vocabulary for asking the bot to explain, check, or prepare future actions. WP13 defines the command surface and a deterministic local parser, but it does not execute commands.

This work package is report-only because OpenVA bot authority, queue enforcement, failure routing, and dashboard reporting should be observable before any GitHub comment listener can mutate repository state. The parser emits command decisions that future GitHub automation may consume after a separate authority-expansion PR.

## Command Syntax

Commands must use the `/openva` prefix and an exact command name:

```text
/openva retry-source-preflight
/openva defer-candidate
/openva promote-reviewed-plan
/openva explain-strict-growth
/openva quarantine-source
/openva recheck-final-url
/openva hold
/openva unhold
```

Aliases are not enabled in WP13. Unknown `/openva` commands are denied. Non-OpenVA comments are ignored. Multiple `/openva` commands in one comment are denied until batching semantics are explicitly defined.

## Command Lifecycle

The WP13 lifecycle is:

1. Read a maintainer comment.
2. Detect whether it contains one `/openva` command.
3. Normalize the command.
4. Validate the actor role.
5. Validate the command contract entry.
6. Validate lane authority.
7. Record whether a queue check or failure-router check is required later.
8. Emit a report-only command decision.

Every command remains `executable: false`. Hold and unhold are parsed, but they are not applied.

## Actor Authorization

WP13 requires the actor role `maintainer`. Future work may distinguish source maintainers, reviewers, or contributors for explanation-only commands, but this first command surface uses maintainer authorization as the safe default.

Commands from any other actor role are denied. The parser does not call GitHub APIs to discover roles; the caller must provide the local `--actor-role` value.

## Lane Authority Checks

Each command maps to a WP9 lane in `docs/operations/contracts/bot-authority.yaml`. The parser verifies that the lane exists and that the command is declared in `docs/operations/contracts/bot-chatops.yaml`.

Report-only commands must not mutate catalog truth. Commands that would eventually write branches, open PRs, apply labels, dispatch workflows, update issues, or change hold state remain planned and non-executable in WP13.

## Queue Checks

Commands that may lead to source repair, controlled promotion, or support PR work can require a later WP11 queue check. The chat-ops decision records the queue lane that future automation must evaluate before taking any write-capable action.

The parser does not run the queue enforcer by itself and does not enforce queue limits.

## Failure-Router Integration

Commands that retry, explain, recheck, quarantine, hold, or unhold failure-related state can require WP12 failure-router context. The chat-ops decision records that requirement, but the parser does not classify failures by itself.

## Audit Output

Every accepted command requires a chat-ops decision report. The report includes the raw comment, normalized command, actor role, authorization result, lane ID, side-effect class, executable flag, report-only flag, queue/failure-router requirements, decision, reasons, next safe action, and audit artifacts.

## Unknown Command Behavior

Unknown `/openva` commands are denied by default. The parser does not infer intent from near matches, misspellings, or extra arguments. Commands must be exact unless an alias is explicitly declared in the contract.

## Hold And Unhold

`/openva hold` and `/openva unhold` are planned control commands. WP13 only parses them and records a report-only decision. It does not apply labels, change dashboard issue state, pause queues, resume queues, or update GitHub issues.

## Future GitHub Integration

A later implementation may listen to GitHub comments, call this parser, publish the decision report, and then call the queue enforcer or failure router. That future implementation must still obey WP9 bot authority, WP10 dashboard posture, WP11 queue decisions, and WP12 failure routing. WP13 itself performs no GitHub API calls.
