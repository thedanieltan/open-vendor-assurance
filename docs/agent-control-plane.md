# Agent Control Plane

OpenVA supports agent-assisted maintenance through bounded, reviewable workflows.

The control plane defines what agents may do autonomously, what they may propose through pull requests, and where human review is mandatory.

## Operating principle

Agents may discover, observe, compile, generate, validate, and propose.

Agents must not bypass source access controls, commit directly to `main`, auto-merge, make legal or compliance conclusions, scrape gated materials, or weaken OpenVA's public-source and non-advisory boundaries.

## Agent classes

### Catalog curator agent

Purpose:

```text
expand the public vendor catalog through bounded catalog batches
```

Allowed outputs:

```text
catalog-batches/{theme}.yaml
data/vendors/**
indexes/**
openva-pack.json
Catalog: PRs
```

Required commands:

```bash
python -m tools.openva.catalog_batch catalog-batches/{theme}.yaml --build-indexes
python -m tools.openva.validate validate
pytest -q
```

Human review is required before merge.

### Source refinement agent

Purpose:

```text
review observation reports and propose better public source URLs when current sources fail, move, or trigger bot protection
```

Allowed outputs:

```text
Catalog: update {vendor-id} public source metadata
Catalog: update source-quality batch
```

The agent may propose replacements only when the replacement is public, vendor-controlled, and more specific than the existing source.

### Observation review agent

Purpose:

```text
summarize scheduled observation reports and prepare human-review queues
```

Allowed outputs:

```text
issue comments
review queue summaries
non-mutating reports
```

The agent must not write ambiguous observations by default.

### Backlog curator agent

Purpose:

```text
maintain candidate expansion themes and coverage gaps
```

Allowed outputs:

```text
docs/vendor-expansion-backlog.md
catalog-batches/backlog/**
coverage summaries
```

The backlog curator does not add vendors unless separately assigned to a catalog batch.

### Release readiness agent

Purpose:

```text
check release, validation, generated-file, and workflow readiness
```

Allowed outputs:

```text
release-readiness comments
core PRs when explicitly assigned
```

The release readiness agent must not change catalog records unless explicitly assigned.

## Agent setup matrix

Use these prompt files as the starting instruction set for autonomous or semi-autonomous runs:

| Agent | Prompt | Primary automation | Default mutation posture |
| --- | --- | --- | --- |
| Catalog curator | `prompts/catalog-curator-agent.md` | `catalog-agent-pr`, `candidate-promotion-pr` | PR-only catalog changes |
| Source refinement | `prompts/source-refinement-agent.md` | `source-refinement-queue`, source maintenance workflows | PR-only source metadata fixes when clear |
| Observation review | `prompts/observation-review-agent.md` | `observe-report`, `source-refinement-queue` | Non-mutating summaries |
| Backlog curator | `prompts/backlog-curator-agent.md` | `catalog-growth-discovery` | Planning files only |
| Release readiness | `prompts/release-readiness-agent.md` | `release-candidate`, validation workflows | Non-catalog release reports by default |

Agents that produce catalog changes must use `Catalog:` pull requests and must keep human review at the source-authority boundary.

## Automation levels

### Fully automated

The following may run without maintainer approval:

```text
validation
index freshness checks
catalog guard
pack integrity checks
URL safety checks
observation dry-run reports
coverage statistics
backlog statistics
workflow inventory reports
```

### Agent-proposed

The following may be proposed through pull requests or issues:

```text
vendor batch manifests
generated catalog records
source URL corrections
coverage/backlog updates
observation review summaries
release-readiness findings
workflow review findings
```

### Human-gated

The following require maintainer approval:

```text
merging to main
schema changes
workflow changes
source-policy changes
official publisher exceptions
non-English uncertain interpretation
writing ambiguous observations
handling gated or bot-protected sources
release tagging
repository visibility changes
```

## Branch naming

Use descriptive agent-owned branch names:

```text
agent-{agent-name}-{theme}
```

Examples:

```text
agent-catalog-curator-identity-security
agent-source-refinement-observation-fixes
agent-backlog-curator-apac-saas
```

Avoid generic or sequence-only names such as:

```text
20
catalog
next
main-work
```

## Pull request naming

Catalog PRs must use:

```text
Catalog: add {theme} vendor batch
Catalog: update {theme} source metadata
```

Core PRs should use:

```text
{area}: {core change}
```

Do not use internal phase labels in public-facing PR titles, docs, or descriptions.

## Stop conditions

Agents must stop and request maintainer review when:

- a useful source requires login, CAPTCHA, NDA, sales approval, customer status, support ticket access, or portal access;
- a source is not clearly vendor-controlled, regulator-controlled, or standards-body-controlled;
- a source requires an official-publisher exception;
- vendor legal identity is ambiguous;
- non-English source interpretation is uncertain;
- validation fails;
- generated files drift unexpectedly;
- a proposed catalog PR would touch schemas, tools, tests, workflows, governance, policy, README, SECURITY, LICENSE, or CODEOWNERS;
- the change could affect pack guarantees, observation behavior, or release posture.

## Non-advisory boundary

Agents must not describe vendors or sources as:

```text
compliant
safe
approved
adequate
recommended
suitable
low risk
high risk
verified by OpenVA
certified by OpenVA
```

Agents may only describe source facts, such as:

```text
Vendor publishes a public security page.
Vendor publishes a public DPA page.
The source is a public trust-center landing page.
```

## Default operating loop

A low-human-intervention OpenVA loop should run as follows:

```text
1. Observation report runs on a schedule.
2. Observation review agent summarizes ambiguous sources.
3. Source refinement agent proposes source fixes where public alternatives exist.
4. Catalog curator agent proposes one bounded vendor batch.
5. CI validates generated files, guardrails, and tests.
6. Maintainer reviews source authority and merges clean PRs.
7. Backlog curator updates coverage gaps.
8. Release readiness agent checks pack, fixture, workflow, and release posture.
9. Workflow review confirms automation remains useful and non-duplicative.
```

The human role should focus on trust boundaries, not repetitive YAML production.
