# OpenVA Documentation Index

This index helps contributors, maintainers, catalog agents, and downstream consumers find the right OpenVA document quickly.

## Project boundary

Read these first to understand what OpenVA is and is not:

```text
README.md
DISCLAIMER.md
GOVERNANCE.md
CONTRIBUTING.md
SECURITY.md
```

## Public launch and governance

```text
docs/v0.1.0-public-launch-readiness.md
docs/public-launch-checklist.md
docs/public-launch-cutover.md
docs/v0.1.0-release-candidate.md
docs/roadmap.md
docs/triage-policy.md
docs/first-good-issue-policy.md
docs/ci-and-branch-protection.md
MAINTAINERS.md
```

## Review operations

```text
docs/human-review-operations.md
docs/source-refinement-workflow.md
docs/observation-reporting.md
docs/agent-control-plane.md
docs/agent-runbook.md
```

## Catalog contribution workflow

```text
docs/catalog-agent-protocol.md
docs/catalog-batch-generator.md
docs/breadth-depth-operating-model.md
docs/category-coverage-program.md
docs/category-lane-execution-backlog.md
config/category-taxonomy.yaml
docs/coverage-map.md
docs/vendor-expansion-backlog.md
docs/public-update-pathway.md
docs/vendor-public-manifest.md
```

## Observation workflow

```text
docs/observation-pilot.md
docs/observation-result-taxonomy.md
config/observation-pilot.yaml
```

## Consumer and importer workflow

```text
docs/consumer-conformance-fixtures.md
docs/versioning-policy.md
docs/release-policy.md
docs/release-checklist.md
fixtures/packs/
openva-pack.json
indexes/
schemas/openva/
```

## Policies

```text
policy/scope.md
policy/non-advisory-policy.md
policy/public-sources-only.md
policy/language-policy.md
policy/retention-policy.md
policy/controlled-vocabulary.yaml
```

## Validation commands

Every core change should pass:

```bash
python -m tools.openva.validate validate
pytest -q
```

Before release or pack pinning, run:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

## Non-advisory reminder

OpenVA records public-source metadata. It does not approve, recommend, certify, score, or determine whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.
