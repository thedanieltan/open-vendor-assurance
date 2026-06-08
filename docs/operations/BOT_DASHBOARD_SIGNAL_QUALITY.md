# OpenVA Bot Dashboard Signal Quality

WP24 improves dashboard readability without increasing bot authority.

The goal is to help maintainers distinguish blocking issues, actionable work, watch items, informational telemetry, and missing optional local artifacts. A useful bot dashboard must not make every signal look equally urgent.

## Signal classes

The dashboard contract defines these signal classes:

| Class | Meaning |
|---|---|
| `blocking` | Must be resolved before write-capable bot actions continue. |
| `action_required` | Maintainer action is required before the next controlled operation. |
| `watch` | Monitor or refresh evidence before relying on the signal. |
| `informational` | Useful context that does not require immediate action. |
| `missing_optional_input` | Optional local evidence is unavailable and must not be treated as a critical failure. |
| `unknown` | Signal could not be classified and should remain advisory. |

Signals sort by class rank. Blocking signals render before action-required signals, which render before watch and informational signals. Missing optional inputs render below operational signals because they are evidence gaps, not proof of failure.

## Signal Quality Summary

The dashboard includes a `Signal Quality Summary` section near the top. It ranks the current dashboard posture before the detailed sections.

This section is intended to answer:

- Is there anything blocking write-capable bot action?
- Is there a specific maintainer action required?
- Are missing artifacts merely unavailable local evidence?
- What is the highest-priority next safe action?

## Priority model

The dashboard contract also declares a deterministic priority model for signals that can otherwise create noise.

The required order is:

1. Queue pause switches, queue denials, and policy stops before queue deferrals.
2. Failure-router stop-lane results before retryable failures.
3. Denied or unsafe chat-ops commands before ignored comments.
4. Workflow-retirement blockers before future retirement candidates.
5. Missing optional inputs outside the blocker lane unless the contract marks the input required.

This model is deliberately presentational. It does not enforce queues, execute chat-ops commands, mutate labels, open PRs, merge PRs, dispatch workflows, retire workflows, or write catalog truth.

## Missing optional artifacts

Missing optional artifacts must not create false critical posture. They indicate that a local checkout does not have a generated report, not that the corresponding workflow failed.

The dashboard still lists them, but classifies them as `missing_optional_input` unless the contract later marks them required.

## No authority expansion

WP24 does not:

- enable live label mutation
- execute new chat-ops commands
- change queue enforcement behavior
- change failure-router taxonomy beyond presentation mapping
- retire workflows
- mutate catalog data
- dispatch workflows
- widen workflow permissions

## Operator use

Operators should read the dashboard in this order:

1. Review the `Signal Quality Summary`.
2. Resolve any `blocking` signals.
3. Handle `action_required` signals before controlled promotion or source repair.
4. Treat `watch` signals as evidence-refresh prompts.
5. Treat `missing_optional_input` as a local evidence gap, not a failure.
6. Use the `Next Safe Action` only if it is consistent with bot authority and reviewed evidence.
