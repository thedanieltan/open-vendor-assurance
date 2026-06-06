# Catalog Autonomy Policy

OpenVA separates public-source metadata from assurance conclusions.

Agents may autonomously maintain verified public source-location facts, registry-backed entity facts, and vendor-source-attested relationship facts when the evidence is explicit, bounded, and machine-verifiable. Agents must not make legal, compliance, procurement, security, KYC, AML, sanctions, approval, suitability, vendor-risk, or certification-validity conclusions.

## Current state and target state

This policy describes both the current operating state and the approved target design for catalog growth autonomy.

Current state:

```text
strict-growth-latest may generate a Catalog PR
strict-growth-latest must not imply automerge eligibility
machine-canonical, P0 source repair, and strict-growth are implemented automerge jobs
strict-growth automerge execution is wired through its dedicated lane
```

Target state after calibration:

```text
strict-growth-latest may generate bounded Catalog PRs
strict-growth PRs may become eligible only through a dedicated automerge:strict-growth lane
strict-growth must not inherit automerge:machine-canonical authority
strict-growth merge execution is activated only after a separate calibration/activation PR
```

## Authority ladder

OpenVA uses this authority ladder:

```text
Discovery Intake Loop
  discovers, classifies, queues, and reports candidates
  does not write canonical catalog records

Strict Autonomous PR Lane
  generates bounded Catalog PRs for strict source-attested or registry-attested facts
  does not merge by default

Human Review Lane
  handles ambiguous, inferred, conflicting, high-impact, or policy-exception cases

Automerge Lanes
  merge only explicitly labeled, policy-gated, machine-verifiable PR classes

PR Safety Loop
  enforces validators, source preflight, generated drift checks, tests, and branch protection
```

A bot opening a PR does not imply that the PR is eligible for automerge.

## Enforcement mode

The repository automerge policy is configured in:

```text
config/automerge-policy.yaml
```

Automerge eligibility checks may run in report-only mode for diagnostics, but report-only output is never merge authority. An automerge workflow may treat a lane as merge-eligible only when the relevant checker runs in enforce mode and returns eligible.

## Checker input interface

Strict-growth eligibility has two interfaces:

```text
Python API: parsed dictionaries plus SHA/label context
CLI: file paths that are loaded into the same parsed-dictionary checker
```

The Python checker should receive:

```text
promotion_plan: dict
eligibility_report: dict | None
labels: list[str]
current_head_sha: str
recorded_head_sha: str
current_base_sha: str
recorded_base_sha: str | None
now: datetime
policy: dict
```

The CLI may accept file paths, but it must load them and call the parsed-dictionary checker. This keeps tests stable and avoids one-off file-path logic in the eligibility rules.

## Freshness policy

Automerge eligibility is time-sensitive.

Strict growth has a 4-hour freshness window because it can create new vendor/source/entity catalog state and has higher blast radius.

Generated output sync has a 24-hour freshness window because generated outputs are deterministic artifacts derived from canonical inputs.

Freshness clock source:

```text
strict-growth freshness uses the strict-growth evidence bundle timestamp, not the PR event timestamp
generated-output freshness uses the generated artifact manifest timestamp, not the PR event timestamp
```

For strict growth, the evidence bundle timestamp is:

```text
primary: strict-growth eligibility report generated_at
fallback: strict-growth promotion plan generated_at, only when no eligibility report is supplied
```

If both an eligibility report and a promotion plan are supplied, the eligibility report timestamp is authoritative. A promotion plan timestamp may be later when the plan is regenerated from the eligibility report in the same SHA-bound workflow run; freshness still uses the eligibility report timestamp.

The PR event timestamp is only the time the checker runs. It does not refresh evidence.

Freshness checks distinguish head and base movement:

```text
head SHA mismatch = hard failure
base SHA mismatch = warning unless current validation has already evaluated the latest base
expired evidence = hard failure for automerge eligibility
```

Head SHA movement means the PR diff changed and strict-growth eligibility must be recomputed. Base SHA movement can be benign when another PR merged to `main`, so it is not automatically equivalent to a changed strict-growth diff.

Rerun triggers:

```text
pull_request opened
pull_request synchronize
pull_request reopened
pull_request labeled
pull_request ready_for_review
manual workflow rerun
branch update from main
```

If a strict-growth PR goes stale only because time elapsed, maintainers may rerun the relevant workflow, update the branch from `main`, push a no-op commit, or remove the automerge label.

## Catalog layers

### 1. Observation layer

Autonomous.

Observation records are public-source fetch facts, such as URL fetch success, redirects, 404/410, bot protection, gating, hash changes, or candidate URL discovery.

Observation records are non-canonical.

```text
canonical: false
catalog_tier: observation
review_state: auto_observed or human_review_required
advisory_boundary: non_advisory
```

### 2. Candidate source layer

Autonomous discovery is allowed.

Candidate source records are not canonical until they pass the relevant promotion gates.

```text
canonical: false
catalog_tier: discovery
review_state: human_review_required or strict_pr_candidate
advisory_boundary: non_advisory
```

### 3. Machine-validated canonical source layer

Autonomous promotion is allowed only for public source-location facts that pass all machine-canonical gates.

Machine-validated canonical means OpenVA recognizes the URL as a public source reference for the vendor.

It does not mean the vendor is compliant, approved, safe, certified, suitable, low-risk, or recommended.

```text
record_class: canonical
canonical: true
catalog_tier: machine_validated
review_state: auto_validated
advisory_boundary: non_advisory
```

### 4. Registry-backed legal entity layer

Autonomous promotion is allowed only when the legal entity fact is backed by a public statutory registry or equivalent official registry source.

Allowed registry-backed facts include:

```text
legal name
registration number
registry jurisdiction
registry authority
registry source URL
```

Registry-backed legal entity records do not determine legal sufficiency, contracting outcome, vendor suitability, or customer-specific agreement status.

### 5. Source-attested relationship layer

Autonomous promotion is allowed only when the relationship is explicitly stated by a vendor public source or statutory registry source.

Allowed strict-growth relationship records must use source-attested naming:

```text
vendor_stated_*
registry_stated_*
```

Examples:

```text
vendor_stated_terms_publisher
vendor_stated_website_operator
vendor_stated_regional_operator
vendor_stated_contracting_entity
registry_stated_registered_entity
```

OpenVA records that the public source states the relationship. OpenVA does not independently infer the legal meaning or customer-specific consequence of that relationship.

### 6. Human-reviewed canonical layer

Human review remains required for ambiguous, inferred, conflicting, high-impact, or policy-exception cases.

```text
record_class: canonical
canonical: true
catalog_tier: human_reviewed
review_state: human_reviewed
advisory_boundary: non_advisory
```

## Machine-canonical gates

A candidate source may become machine-validated canonical only if all are true:

1. Vendor exists in OpenVA, unless the candidate is going through the dedicated strict-growth lane.
2. Candidate URL uses HTTPS.
3. Candidate URL is public.
4. Candidate URL does not require login, NDA, customer status, sales approval, private portal access, support-ticket access, form submission, CAPTCHA, anti-bot bypass, or credentialed access.
5. Fetch result is successful, or redirect is safe.
6. Safe redirect means same registrable domain or explicitly known vendor-controlled domain.
7. Final URL remains public.
8. Source type is recognized.
9. Source type has path, title, content, or matched-term evidence.
10. No raw vendor document mirroring is introduced.
11. No extracted full text is committed.
12. No advisory wording is introduced.
13. Provenance is recorded.
14. Generated indexes and pack are rebuilt.
15. Validation and tests pass.

## Strict-growth gates

`strict-growth-latest` is an autonomous PR-generation lane, not an automerge lane by itself.

Strict-growth automerge must use a dedicated label:

```text
automerge:strict-growth
```

and must also require:

```text
catalog-growth
```

Strict-growth must not use `automerge:machine-canonical`.

Strict-growth limits:

```text
max_new_vendors_per_pr: 5
max_sources_per_new_vendor: 2
freshness_window: 4 hours
core_source_types_only: dpa, subprocessors_list, privacy_notice, security_page
```

Strict-growth remains source-location-first for source-role coverage. It must not infer `coverage_claims` from broad page titles such as trust center, security, legal, or compliance. A strict-growth plan may carry `coverage_claims` only when the role evidence is explicit, non-advisory, machine-supported, and already present in the reviewed plan data passed to the promotion path.

Strict-growth eligibility is batch-level: if any action in the batch fails a strict-growth gate, the entire PR is ineligible for `automerge:strict-growth`.

Strict-growth action identifiers are stable semantic IDs, not positional indexes. The configured action identifier fields are:

```text
vendor.candidate_vendor_id
source.source_type_candidate
source.candidate_source_id
```

Reason codes should use this format:

```text
<reason_code>:<candidate_vendor_id>:<source_type_candidate>:<candidate_source_id>
```

If one of those fields is missing, the checker should use `missing` for that segment and also emit the relevant missing-field reason.

Strict-growth eligibility requires all of these:

1. Every action has `strict_machine_candidate: true` at the action level.
2. `strict_machine_candidate: true` is necessary but never sufficient by itself.
3. A missing, false, null, or non-boolean `strict_machine_candidate` on any action fails the entire strict-growth PR.
4. No action is `review_required`, `deferred`, `rejected`, or ambiguous.
5. Source types are limited to the approved core source types.
6. New-vendor and per-vendor source caps are not exceeded.
7. Candidate IDs and official domains do not conflict with existing catalog records.
8. Source preflight passes.
9. Repository validation passes.
10. Generated outputs are rebuilt and drift-free.
11. Freshness check passes.
12. Report-only mode is not used as merge authority.
13. Entity or relationship records, if present, are source-attested or registry-attested and inference-free.

## Deny-first inference policy

Strict-growth uses a deny-first inference rule.

Any blocked inference signal fails strict-growth eligibility, even if another field claims source or registry attestation.

Allowed strict-growth attestation values:

```text
attestation_mode: source_attested
attestation_mode: registry_attested
```

Allowed strict-growth inference values:

```text
inference_mode: none
inference_mode: explicit_source_statement
```

Blocked strict-growth inference values include:

```text
inference_mode: domain_similarity
inference_mode: name_similarity
inference_mode: group_affiliation_inferred
inference_mode: third_party_assertion
inference_mode: model_inferred
inference_mode: unknown
```

For strict-growth entity or relationship records, `attestation_mode` and `inference_mode` are mandatory. An absent `inference_mode` fails strict-growth eligibility. An absent `attestation_mode` fails strict-growth eligibility. Absence is not treated as `none`.

If both allowed and blocked inference signals are present, the blocked signal wins.

Evidence requirements:

```text
source_attested requires evidence_url and source_id
registry_attested requires registry_source_url and registry_authority
```

## Human-review-only cases

Human review is required for:

```text
cross-domain redirects unless explicitly allowlisted
relationship inference
legal-effect interpretation not directly stated by source
ambiguous legal entity mapping
contracting entity ambiguity
authority classification ambiguity
new source type creation
gated sources
jurisdiction-specific assertions not directly source-attested
conflicting candidates
security, certification, KYC, AML, or sanctions interpretation
vendor deletion
source authority class changes
advisory or meaning-level claims
large promotion batches outside strict caps
```

## Backlog policy

Catalog-growth backlog artifacts are operational memory, not promotion prerequisites and not catalog truth.

Backlog states:

```text
strict_pr_candidate
human_review_required
deferred
rejected
expired
```

Discovery cadence is weekly. Expiry policy is therefore expressed in days and discovery cycles:

```text
strict_pr_candidate: expires after 21 days or 3 discovery cycles
human_review_required: refresh required after 42 days or 6 discovery cycles
deferred: refresh required after 84 days or 12 discovery cycles
rejected: suppress rediscovery for 90 days unless source evidence changes
```

The expiry clock resets only when new discovery evidence is generated for the same candidate.

A workflow rerun with identical evidence refreshes `generated_at` but must retain the same `evidence_hash`. If `evidence_hash` is unchanged, the backlog item is refreshed but not upgraded. If `evidence_hash` changes, the item is reclassified.

Backlog review cadence:

```text
catalog-growth-discovery runs weekly
maintainers review backlog during weekly maintenance or release preparation
expired strict candidates must be refreshed before strict PR generation
```

## Auto-merge lanes

OpenVA recognizes these lanes:

```text
automerge:generated
automerge:observation
automerge:machine-canonical
automerge:p0-source-repair
automerge:strict-growth
needs-human-review
blocked-by-scope
```

`automerge:generated` is allowed only for deterministic generated artifacts.

`automerge:observation` is allowed only for non-canonical observation artifacts.

`automerge:machine-canonical` is allowed only for bounded machine-verifiable catalog metadata changes that pass all machine-canonical gates and stay within the configured diff threshold.

`automerge:p0-source-repair` is allowed only for confirmed source repair evidence, requires `source-refinement`, and remains capped at 10 source records per PR.

`automerge:strict-growth` is a dedicated lane for strict catalog growth. It is policy-defined, testable, and wired through `agent-automerge.yml` after successful calibration. It must not inherit `automerge:machine-canonical` authority.

Anything outside the approved automerge lanes requires `needs-human-review`.

## Strict-growth calibration gate

Strict-growth merge execution was activated only after a separate calibration/activation PR.

The calibration PR must include this explicit maintainer decision surface:

```md
## Strict-growth calibration decision

Maintainer: @<github-username>
Decision: approve activation / reject activation / extend calibration
Date: YYYY-MM-DD
Calibration PR: #<number>
Evidence reviewed:
- strict-growth eligibility report
- generated Catalog PR diff
- source preflight report
- validation result
- generated drift check
- full test result
Policy changes required before activation:
- none / list required changes
```

A normal GitHub approval is not enough. The calibration decision must be recorded in the PR body or as a top-level PR comment using the template above.

Calibration success criteria:

1. `strict-growth-latest` opens a bounded Catalog PR without human-authored reviewed plan input.
2. The generated PR changes only allowed catalog/generated paths.
3. The PR contains no more than 5 new vendors.
4. No vendor has more than 2 promoted sources.
5. Every promoted action has `strict_machine_candidate: true`.
6. `strict_machine_candidate: true` alone is rejected when labels, evidence, or freshness are missing.
7. All promoted sources are core source types only.
8. No `review_required`, `deferred`, `rejected`, or ambiguous candidates are applied.
9. Entity/relationship records, if any, are source-attested or registry-attested with allowed inference mode.
10. Head SHA mismatch fails strict-growth eligibility.
11. Expired evidence older than 4 hours fails strict-growth eligibility.
12. Base SHA mismatch produces the documented warning behavior, not a noisy hard failure.
13. Report-only output cannot enable merge authority.
14. The PR passes validation, source preflight, generated drift checks, and full tests.
15. A maintainer records the explicit calibration decision using the decision template above.

## Launch posture

OpenVA agents may autonomously verify and canonicalize public source references, registry-backed entity facts, and vendor-source-attested relationship facts under strict gates. OpenVA does not autonomously make assurance, risk, legal, procurement, or compliance conclusions.
