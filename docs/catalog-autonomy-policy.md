# Catalog Autonomy Policy

OpenVA separates source-location facts from assurance conclusions.

Agents may autonomously maintain verified public source-location facts. Agents must not make legal, compliance, procurement, security, KYC, AML, sanctions, approval, suitability, vendor-risk, or certification-validity conclusions.

## Enforcement mode

The auto-merge workflow ships in report-only mode for v0.1.

The eligibility checker may report that a PR would qualify for an autonomous lane, but it does not merge PRs. Actual merge activation requires a separate PR updating the merge policy, workflow permissions, and enforcement mode after calibration criteria are met.

The current machine-canonical blast-radius limit is:

```text
maximum 50 source records per PR
```

This value is configured in `config/automerge-policy.yaml`.

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

Candidate source records are not canonical until they pass the machine-canonical gates in this policy.

```text
canonical: false
catalog_tier: discovery
review_state: human_review_required
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

### 4. Human-reviewed canonical source layer

Human review remains required for meaning-level, ambiguous, legal-entity, authority, jurisdictional, certification, security, KYC/AML, sanctions, or high-impact changes.

```text
record_class: canonical
canonical: true
catalog_tier: human_reviewed
review_state: human_reviewed
advisory_boundary: non_advisory
```

## Legacy canonical default

Existing canonical source records without explicit `catalog_tier` are treated as `human_reviewed` by default. This reflects the review posture at v0.1.0. A future migration may make these fields explicit.

## Machine-canonical gates

A candidate source may become machine-validated canonical only if all are true:

1. Vendor exists in OpenVA.
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

## Human-review-only cases

Human review is required for cross-domain redirects unless explicitly allowlisted, legal entity mapping, contracting entity resolution, authority classification ambiguity, new source type creation, gated sources, jurisdiction-specific assertions, conflicting candidates, security, certification, KYC, AML, or sanctions interpretation, vendor deletion, source authority class changes, and any advisory or meaning-level claim.

## Auto-merge lanes, report-only

OpenVA recognizes these lanes:

```text
automerge:generated
automerge:observation
automerge:machine-canonical
needs-human-review
blocked-by-scope
```

The lanes are report-only in v0.1.

`automerge:generated` is allowed only for deterministic generated artifacts.

`automerge:observation` is allowed only for non-canonical observation artifacts.

`automerge:machine-canonical` is allowed only for candidate-to-machine-canonical source reference promotions that pass all machine-canonical gates and stay within the configured diff threshold.

Anything outside the report-only auto-merge lanes requires `needs-human-review`.

## Launch posture

OpenVA agents may autonomously verify and canonicalize public source references under strict gates. OpenVA does not autonomously make assurance, risk, legal, procurement, or compliance conclusions.
