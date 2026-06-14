# Governance

open-vendor-assurance is maintained as a public-good metadata registry for public vendor assurance references.

It is not a legal, compliance, procurement, security, KYC, AML, or vendor-risk advisory service.

## Governance principles

Maintainers must preserve the following project boundaries:

- public-source-only;
- metadata-first;
- factual and non-advisory;
- native-language-aware;
- no private customer materials;
- no gated trust-center contents;
- no vendor scoring or approval claims;
- no tenant-specific compliance decisions.

## Maintainer duties

Maintainers are responsible for:

- enforcing public-source-only rules;
- reviewing schema and vocabulary changes;
- reviewing rights classification changes;
- reviewing access classification changes;
- reviewing non-English source interpretation;
- rejecting advisory, promotional, or conclusory wording;
- ensuring generated indexes are reproducible;
- keeping automation constrained to pull-request proposals;
- applying issue and PR triage rules consistently.

See also:

```text
MAINTAINERS.md
docs/triage-policy.md
docs/public-launch-checklist.md
```

## Autonomous catalog operation

Routine catalog growth and maintenance run **autonomously** through pull
requests and do **not** require human approval. This includes routine new
vendors, new sources, source repair, quarantine, machine-provisional
materialisation, quorum promotion, and rollback of machine-created state. Each
runs through the standard path — branch → pull request → authority checks →
path checks → validation → release gate → delay where required → controlled
automerge — and every machine-created claim links to a committed machine
decision and a reversal reference (see
`docs/catalog-autonomy-policy.md` and `config/bot-constitution.yaml`).

When evidence is insufficient, conflicting, gated, or ambiguous, the system
**fails closed** to `deferred`, `rejected`, `quarantined`, or `rolled_back`. It
never converts a routine catalog record into a human-review queue.

## Human review required

Humans govern the *rules*, not routine records. Human review is required for:

- code changes;
- schema changes;
- workflow changes;
- machine-readable authority and bot-constitution changes;
- policy thresholds;
- permissions and credentials;
- export compatibility profiles;
- the emergency hold.

Human review also remains required for the genuinely non-routine catalog cases
that the autonomous lanes deliberately defer rather than decide: KYC, AML,
sanctions, or regulated-finance records; legal-effect or authority
interpretation; non-English summary interpretation flagged as uncertain; and
vendor deletion. These are deferred by the machine, not silently auto-approved.

## Pull request lanes

### Core lane

Core-lane PRs may affect schemas, validators, pack contracts, observation behavior, workflows, governance, security posture, conformance fixtures, and release semantics.

Core-lane PRs require maintainer review.

### Catalog lane

Catalog-lane PRs should start with:

```text
Catalog:
```

Catalog-lane PRs must follow:

```text
docs/catalog-agent-protocol.md
```

They should remain metadata-only and small, normally three to five vendors per PR.

## Automation rule

Automation discovers sources, computes hashes, detects changes, materialises and
promotes routine catalog records, repairs or quarantines failing sources, rolls
back invalid machine-created state, and opens pull requests. Routine catalog
mutation is autonomous; it is governed by machine decisions, separation of
duties, release gates, and controlled automerge — not by a human approval step.

Automation must not:

- merge directly to main (all mutation flows through pull requests);
- classify legal sufficiency;
- score vendor risk;
- approve, recommend, or rank vendors;
- summarize private or gated materials;
- bypass access controls, CAPTCHA, WAF, or bot protection;
- rewrite project doctrine, schemas, workflows, authority, or policy thresholds
  without human review.

## Dataset maturity

Records are best-effort public metadata. A record being present in OpenVA does not mean a vendor is approved, compliant, suitable, or recommended.

## Public launch posture

Before public launch, maintainers should confirm the checklist in:

```text
docs/public-launch-checklist.md
```

Open issues and PRs that could confuse the project boundary should be triaged, labelled, closed, or documented before launch.
