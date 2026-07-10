# OpenVA documentation

Use this index to find the current public, contributor, consumer, and operating documents without reading historical implementation records first.

## Start here

```text
README.md
docs/licensing.md
DISCLAIMER.md
CONTRIBUTING.md
GOVERNANCE.md
SECURITY.md
docs/roadmap.md
```

These documents define what OpenVA is, how it may be reused, and the non-advisory public-source boundary.

## Use OpenVA

```text
docs/release-downloads.md
docs/local-compiler.md
docs/resolver-api.md
docs/agent-integrations.md
docs/agent-workspace-composition.md
integrations/mcp/openva_mcp/README.md
```

The browser resolver is available at:

```text
https://thedanieltan.github.io/open-vendor-assurance/
```

## Contribute public vendor and source metadata

```text
docs/submission-intake.md
docs/submission-verification.md
docs/catalog-agent-protocol.md
docs/public-update-pathway.md
docs/human-review-operations.md
```

Submit public URLs and factual metadata only. Do not submit private agreements, authenticated portal exports, credentials, copied full text, or customer-specific evidence.

## Public launch and repository governance

```text
docs/public-launch-checklist.md
docs/roadmap.md
docs/triage-policy.md
docs/first-good-issue-policy.md
docs/ci-and-branch-protection.md
docs/versioning-policy.md
docs/release-policy.md
docs/release-checklist.md
MAINTAINERS.md
```

## Consumer and importer contracts

```text
docs/consumer-conformance-fixtures.md
docs/agent-export-contract.md
docs/adapter-contract.md
docs/adapter-output-contract.md
fixtures/packs/
openva-pack.json
indexes/
schemas/openva/
```

## Architecture and workspace control plane

```text
docs/architecture/OPENVA_SYSTEM_DESIGN.md
docs/architecture/SOURCE_REGISTRY_SCHEMA_V1.md
docs/operations/OPENVA_WORKSPACE_OPERATING_MODEL.md
tools/openva/workspace.yaml
.github/validation-ownership.yaml
docs/operations/contracts/workflow-inventory.yaml
```

## Discovery and catalog growth

```text
docs/breadth-depth-operating-model.md
docs/coverage-growth.md
docs/coverage-map.md
docs/vendor-expansion-backlog.md
docs/maintenance/operator-runbook.md
```

The catalog is not capped by vendor count. Network, request, page, and concurrency limits are per-run safety budgets.

## Source observation and maintenance

```text
docs/observation-result-taxonomy.md
docs/source-trust/observation-retention-policy.md
docs/source-trust/SOURCE_TRUST_OPERATIONS_RUNBOOK.md
docs/observation-ledger.md
docs/observation-reporting.md
```

Observation records are fetch-time facts, not vendor ratings or approval decisions.

## Public discovery surface

The GitHub Pages build publishes:

```text
/agents/
/vendors/{vendor_id}/
/.well-known/openva.json
/sitemap.xml
/robots.txt
/llms.txt
```

All OpenVA-owned public URLs derive from `config/publication.yaml`.

## Validation

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.validate validate
pytest -q
python -m tools.openva.conformance fixtures/packs/minimal-valid
python -m tools.openva.conformance fixtures/packs/valid-bot-protected-observation
```

OpenVA records public-source metadata. It does not approve, recommend, certify, score, or determine whether a vendor is compliant, secure, suitable, adequate, low risk, or high risk.
