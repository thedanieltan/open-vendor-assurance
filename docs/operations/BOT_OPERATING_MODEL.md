# OpenVA Bot Operating Model

This document defines the automation governance layer above the workflow
operating model. Machine-readable authority, queue, failure, and workflow
contracts are authoritative where prose and configuration differ.

OpenVA automation is lane-scoped and deny-by-default. Discovery may propose;
only declared promotion, maintenance, publication, or reversal lanes may write
through pull requests. Unknown lanes and unknown write paths are denied.

## Core principles

- authority is proportional to evidence certainty;
- public-source facts and operational observations remain non-advisory;
- report-only and discovery lanes do not write catalog truth;
- no component may discover, decide, and merge the same claim;
- machine-created catalog state must be evidence-linked and reversible;
- ambiguous, gated, private, conflicting, or meaning-level cases fail closed;
- repository mutations use pull requests and release gates, never direct pushes
  to `main`.

## Authority model

The authority contract is
`docs/operations/contracts/bot-authority.yaml`. Every lane declares its
workflows, authority level, allowed paths, required labels, token permissions,
and audit artifacts.

A lane may exercise only the capabilities explicitly granted to it:

- write branches;
- open or label pull requests;
- enable auto-merge or merge;
- write catalog truth;
- modify declared paths;
- use declared token permissions.

The default posture denies undeclared lanes, undeclared write paths, and catalog
mutation from discovery or report-only lanes.

### Authority levels

- **Level 0 — report-only:** produces reports, issues, comments, or operational
  labels; no catalog-truth, decision, or merge authority.
- **Level 1 — evidence authorship:** may propose catalog or publication state in
  a pull request; cannot approve or merge its own proposal.
- **Level 2 — independent review:** evaluates identity, domain authority, source
  quality, duplication, adversarial concerns, or release gates; holds no write,
  decision, or merge authority alone.
- **Level 3 — decision:** records an append-only machine decision after the
  required independent evidence and separation of duties are satisfied.
- **Level 4 — merge authority:** enables native auto-merge only after required
  checks, labels, delays, and release gates pass.
- **Level 5 — reversal authority:** reverts eligible machine-created state
  through a pull request without rewriting evidence or decision history.

No single bot holds discovery, decision, and merge authority for the same claim.

## Constitution and release gates

`config/bot-constitution.yaml` defines higher-order invariants such as:

- public-source-only evidence;
- no advisory, scoring, ranking, or approval output;
- no raw-document mirroring;
- SHA-256-only OpenVA digests;
- reversibility of machine-created claims;
- no automation writing directly to `main`;
- separation of discovery, decision, review, and merge duties.

`python -m tools.openva.release_gates check` is the consolidated authority gate.
The `pr` profile evaluates deterministic repository state; the `release` profile
also evaluates required runtime evidence. Thresholds live in
`config/release-gates.yaml`.

## Command surface

| Command | Current mode | Boundary |
|---|---|---|
| `/openva retry-source-preflight` | denied/report-only | no workflow dispatch or catalog mutation |
| `/openva defer-candidate` | denied/report-only | no candidate-state mutation outside declared workflows |
| `/openva promote-reviewed-plan` | denied/report-only | no branch or PR creation from chat-ops |
| `/openva explain-strict-growth` | local audit | deterministic explanation only |
| `/openva quarantine-source` | denied/report-only | no source-state mutation from comments |
| `/openva recheck-final-url` | denied/report-only | no network or catalog mutation from comments |
| `/openva hold` | live | add only `openva-hold` to the current issue or pull request |
| `/openva unhold` | live | remove only `openva-hold` from the current issue or pull request |

Commands that could write branches, create pull requests, mutate catalog truth,
or affect auto-merge require a dedicated authority contract and workflow. The
live chat-ops boundary is documented in
`docs/operations/BOT_CHATOPS_EXECUTION.md`.

## Queue and dashboard model

The queue policy is `docs/operations/contracts/bot-queue-policy.yaml`. It limits
open pull requests, daily and weekly bot activity, lane batch sizes, host rate,
domain concurrency, retry cooldowns, and evidence age.

Operational views should show:

- ready, deferred, rejected, and review-required candidates;
- source-health and redirect failures;
- stale evidence and backlog age;
- recent successful and failed runs;
- the next action permitted by lane authority.

Dashboard and issue-sync lanes are visibility surfaces. They do not grant
catalog, promotion, repair, or merge authority.

## Failure taxonomy

The machine-readable taxonomy is
`docs/operations/contracts/bot-failure-taxonomy.yaml`.

| Code | Operating meaning |
|---|---|
| `source_preflight_failure` | Source accessibility, source role, or certainty could not be validated. |
| `redirect_canonicalization_failure` | Redirect authority or canonical final URL is unclear. |
| `duplicate_url_failure` | Candidate overlaps a committed or queued source. |
| `terminology_contract_failure` | Output violates repository terminology rules. |
| `schema_validation_failure` | Contract, catalog, or generated artifact shape is invalid. |
| `generated_drift_failure` | Deterministic outputs do not match canonical inputs. |
| `workflow_input_compatibility_failure` | Workflow inputs do not match the current contract. |
| `automerge_lane_mismatch` | Labels, paths, or PR state do not match the requested merge lane. |
| `external_fetch_instability` | External retrieval is blocked, unstable, rate-limited, or inconsistent. |
| `stale_evidence_failure` | Evidence exceeds the lane's maximum permitted age. |
| `permission_policy_denial` | Requested behavior exceeds declared authority or token posture. |

Each failure class declares retry eligibility, retry policy, escalation target,
hardening-issue behavior, candidate deferral behavior, and whether the lane must
stop.

## Exception ownership

Ambiguous authority, legal-entity relationships, source-role coverage,
domain mismatches, bot-protected pages, and trust-portal-only sources require an
explicit owner and evidence record. An exception that changes catalog truth must
flow through reviewed evidence and a declared promotion or repair lane; it must
not be applied directly from comments, dashboards, or report-only output.

## Policy simulation

Before activating a new write-capable lane, authority expansion, destructive
cleanup, or workflow retirement, produce:

- a dry-run result;
- policy and permission diffs;
- affected paths and expected action counts;
- a blast-radius estimate;
- failure-mode examples;
- a rollback or disable plan.

## Observability

Automation telemetry should be grouped by lane and failure code and include:

- pull requests opened, merged, closed, or blocked before creation;
- human interventions;
- time to merge;
- failures by class;
- candidate conversion;
- source-preflight and redirect-canonicalization rates;
- deferred and review backlog age.

Metrics describe system operation and do not create authority.

## Retirement and sunset rules

Workflows use these lifecycle states:

| Status | Meaning |
|---|---|
| `active` | Current lane with declared authority, owner, tests, and workflow inventory entry. |
| `shadow_report_only` | Comparison or migration lane with no catalog-write authority. |
| `deprecated_callable` | Manual compatibility surface with a replacement and sunset plan. |
| `quarantined` | Temporarily blocked because authority, source certainty, or permissions are unsafe. |
| `retired` | Removed from active operation after replacement and retirement evidence are complete. |

Deprecated and quarantined workflows must not become undeclared authority
expansion paths.

## Security and permission posture

- use the least-privilege token declared for each lane;
- keep discovery and report-only workflows read-only except for explicitly
  declared issue or comment reporting;
- require path restrictions for branch-writing lanes;
- require audit artifacts for permission-sensitive operations;
- do not widen merge authority through informational labels;
- keep release gates and branch protection independent from the component that
  authored the proposed change.

Forbidden without an explicit future contract:

- direct pushes to `main`;
- catalog mutation from discovery or report-only lanes;
- comment commands that create or merge pull requests;
- undeclared workflow deletion, disabling, or renaming;
- widening auto-merge beyond declared lanes.
