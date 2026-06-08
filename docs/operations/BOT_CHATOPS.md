# OpenVA Bot Chat-Ops

OpenVA chat-ops gives maintainers a common command vocabulary for asking the bot to explain, check, or prepare future actions. WP13 defined the command surface and a deterministic local parser. WP21 adds limited local execution for the lowest-risk commands only.

The parser still emits command decisions that future automation may consume. The execution boundary is documented in `docs/operations/BOT_CHATOPS_EXECUTION.md`.

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

The parser lifecycle is:

1. Read a maintainer comment.
2. Detect whether it contains one `/openva` command.
3. Normalize the command.
4. Validate the actor role.
5. Validate the command contract entry.
6. Validate lane authority.
7. Record whether a queue check or failure-router check is required later.
8. Emit a command decision.

WP21 sets only `/openva explain-strict-growth`, `/openva hold`, and `/openva unhold` to `executable: true`. Higher-risk commands remain non-executable.

## Actor Authorization

WP13 requires the actor role `maintainer`. Future work may distinguish source maintainers, reviewers, or contributors for explanation-only commands, but this first command surface uses maintainer authorization as the safe default.

Commands from any other actor role are denied. The parser does not call GitHub APIs to discover roles; the caller must provide the local `--actor-role` value.

## Lane Authority Checks

Each command maps to a WP9 lane in `docs/operations/contracts/bot-authority.yaml`. The parser verifies that the lane exists and that the command is declared in `docs/operations/contracts/bot-chatops.yaml`.

Report-only commands must not mutate catalog truth. Commands that would eventually write branches, open PRs, dispatch workflows, update issues, or change catalog truth remain planned and non-executable. Hold and unhold produce local hold-state audit reports only; they do not mutate labels in WP21.

## Queue Checks

Commands that may lead to source repair, controlled promotion, or support PR work can require a later WP11 queue check. The chat-ops decision records the queue lane that future automation must evaluate before taking any write-capable action.

The parser does not run the queue enforcer by itself and does not enforce queue limits. The WP21 execution layer runs queue evaluation for queue-gated executable commands when local queue state is supplied.

## Failure-Router Integration

Commands that retry, explain, recheck, quarantine, hold, or unhold failure-related state can require WP12 failure-router context. The chat-ops decision records that requirement. The WP21 execution layer routes denied or queue-blocked execution reports through the failure router.

## Audit Output

Every accepted command requires a chat-ops decision report. Executed commands also require a chat-ops execution report. Reports include the raw comment, normalized command, actor role, authorization result, lane ID, side-effect class, executable flag, report-only flag, queue/failure-router requirements, decision, reasons, next safe action, and audit artifacts.

## Unknown Command Behavior

Unknown `/openva` commands are denied by default. The parser does not infer intent from near matches, misspellings, or extra arguments. Commands must be exact unless an alias is explicitly declared in the contract.

## Hold And Unhold

`/openva hold` and `/openva unhold` are limited local execution commands in WP21. They produce deterministic hold-state reports for the `openva-hold` label, but they do not apply labels, change dashboard issue state, pause queues, resume queues, or update issues.

## Future GitHub Integration

A later implementation may listen to comments, call this parser, publish the decision report, and then call the queue enforcer or failure router. That future implementation must still obey WP9 bot authority, WP10 dashboard posture, WP11 queue decisions, and WP12 failure routing. The parser and WP21 local executor perform no remote API calls.
