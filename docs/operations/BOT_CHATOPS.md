# OpenVA Bot Chat-Ops

OpenVA chat-ops provides a small, exact command vocabulary for maintainers. The
parser is deterministic: it does not infer intent from near matches,
misspellings, aliases, or extra arguments.

The machine-readable contract is
`docs/operations/contracts/bot-chatops.yaml`. Live execution boundaries are
documented in `docs/operations/BOT_CHATOPS_EXECUTION.md`.

## Command syntax

Commands use the `/openva` prefix and one exact command name:

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

Unknown commands are denied. Non-OpenVA comments are ignored. Multiple OpenVA
commands in one comment are denied until batching semantics are explicitly
specified.

## Command lifecycle

1. Read the submitted comment.
2. Detect one exact OpenVA command.
3. Normalize the command.
4. validate the supplied actor role.
5. validate the command contract entry and lane authority.
6. record required queue or failure-router checks.
7. emit a deterministic command decision and audit data.
8. execute only when the command contract and live workflow explicitly allow it.

## Current execution modes

| Command | Mode |
|---|---|
| `/openva retry-source-preflight` | report-only |
| `/openva defer-candidate` | report-only |
| `/openva promote-reviewed-plan` | report-only |
| `/openva explain-strict-growth` | local audit execution |
| `/openva quarantine-source` | report-only |
| `/openva recheck-final-url` | report-only |
| `/openva hold` | live, limited label mutation |
| `/openva unhold` | live, limited label mutation |

Hold and unhold may affect only the `openva-hold` label on the current issue or
pull request and only for an authorized GitHub actor. They do not select another
target or label and do not dispatch workflows, write branches, create or merge
pull requests, or mutate catalog data.

## Actor authorization

The deterministic local parser receives an explicit actor role from its caller.
The live workflow relies on GitHub's `author_association` and permits only
`OWNER`, `MEMBER`, or `COLLABORATOR` actors for hold and unhold.

The parser itself does not call GitHub APIs to discover identity or authority.

## Lane authority and queue checks

Each command maps to a declared lane in
`docs/operations/contracts/bot-authority.yaml`. A command cannot acquire more
authority than its lane grants.

Commands that could lead to repair, promotion, retry, or other write-capable
work may declare queue and failure-router requirements. Recording those
requirements does not execute the action. Report-only commands remain unable to
mutate catalog truth.

## Audit output

Every accepted command produces a decision record containing:

- raw and normalized command;
- actor and authorization result;
- lane ID and side-effect class;
- executable and report-only flags;
- queue and failure-router requirements;
- decision, reasons, next safe action, and audit artifacts.

Executed commands also produce an execution audit record. Live accepted and
denied commands post an audit comment on the target issue or pull request.

## Failure behavior

The command surface fails closed:

- unknown or malformed command → denied;
- multiple commands → denied;
- unauthorized actor → denied;
- arguments where none are supported → denied;
- missing lane authority → denied;
- queue or policy failure → no write-capable action.

Any expansion of executable chat-ops requires an explicit contract, least-
privilege permissions, tests, and a bounded rollback plan.
