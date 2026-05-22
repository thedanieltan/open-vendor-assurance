# Weighted Merge Policy

OpenVA uses weighted agent review to separate routine machine-checkable catalog changes from genuine edge cases. The first rollout is advisory only: validators score PRs and post structured comments, but they do not merge, close, or mutate catalog files.

## Scoring Model

Every PR touching catalog records is scored by four independent validators:

| Validator | Max score | Purpose |
|---|---:|---|
| Schema conformance agent | 1 | Schema, adapter-normalized record, new field, and generated-index checks |
| Source accessibility agent | 1 | Public URL accessibility and gating checks |
| Advisory wording agent | 1 | Non-advisory wording and implication-language checks |
| Provenance completeness agent | 1 | Source references and factual provenance checks |

Total possible score: 4 points.

Advisory interpretation:

- `4/4` with no escalation flags: eligible for future automated handling.
- `4/4` with warnings: eligible for future delayed handling.
- Any score below `4` or any escalation flag: human review required.

During advisory rollout, all outcomes are comments and labels only.

## Validator Definitions

### Schema Conformance Agent

Runs catalog validation and adapter-normalized record validation.

Passes when:

- Modified YAML files pass schema validation.
- Adapter-normalized records pass `validate_adapter_record`.
- No new YAML fields are introduced without schema file changes.
- Generated indexes are not manually modified.
- `build-indexes` produces no diff against committed indexes.

Escalates when schema validation fails, generated index drift appears, adapter records fail, or unknown fields are present without schema changes.

### Source Accessibility Agent

Checks every modified `source_url` and `canonical_url`.

Passes when:

- URLs return HTTP 200 or a known redirect to HTTP 200.
- URLs do not require authentication headers.
- URLs are not in `config/domain-blocklist.yaml`.
- URLs do not return bot-protection headers or challenge content.

During calibration, network checks are soft. A 429 is retried once after 60 seconds and then reported as a warning unless it remains a durable escalation signal.

### Advisory Wording Agent

Runs the prohibited term scanner from `docs/automation-rules.md`.

Passes when:

- No prohibited terms appear in non-exempt catalog field values.
- No prohibited field names appear in generated or adapter output.
- Summary fields describe evidence rather than implications.
- Calibration fixtures continue to pass with expected pass/fail/ambiguous outcomes.

Escalates when prohibited terms appear in production contexts, implication language appears, or new field names introduce advisory concepts such as risk, score, rating, approved, compliant, verified, certified, or recommended.

### Provenance Completeness Agent

Checks that factual fields have traceable public-source provenance.

Passes when:

- Every `source_ids` reference resolves.
- `provenance.collected_at` is present and parseable on new source records.
- Canonical legal entities have `verification_source_ids`.
- Matched entity mentions have complete match provenance.
- Lifecycle events have populated `source_ids`.

Escalates when a source reference does not resolve, canonical entity verification is missing, matched mention provenance is incomplete, or a new factual assertion lacks source traceability.

## Future Merge Mechanism

Automation remains disabled until calibration shows acceptable false-positive and false-negative rates.

Future behavior:

- T1/T2 observation and auto-validated records with `4/4` and no escalation may auto-merge immediately.
- T1/T2 records with `4/4` and warnings may auto-merge after a 24-hour window.
- T3 canonical sources and entity promotions with `4/4` may enter a 72-hour community veto window before merge.
- Any score below `4` or any escalation flag blocks merge and opens human review.
- Schema changes, policy changes, workflow changes, governance changes, and release tagging always require explicit human approval.

Future auto-close behavior:

- A PR may auto-close only if schema validation fails, source URLs are unreachable, and no human has commented within 7 days.
- This behavior is disabled during advisory rollout.

## Escalation Queue

Before `agent-weighted-review` is treated as live, create a GitHub Project board with these columns:

- `Needs agent retry`
- `Needs human review`
- `Blocked by policy`
- `Stale`

The workflow can still post labels and comments if the board is unavailable, but stale-close and queue-maintenance policy is not live until the board exists.

Weekly maintenance scans should retry transient failures, comment on stale PRs, and identify auto-close candidates after 14 days of inactivity.

## Governance Safeguard

No agent may modify `GOVERNANCE.md`, `SECURITY.md`, `docs/automation-rules.md`, `docs/weighted-merge-policy.md`, or `policy/**` without explicit human approval from an org admin account.

CODEOWNERS, workflow tests, and validator escalation guard this in repository code. Branch protection must enforce the approval requirement.
