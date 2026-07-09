Work-Package: WP-AUTONOMOUS-OPERATIONAL-PR-CONTROL-PLANE-01

This is not a new roadmap work package. This is a catalog data backfill under the existing catalog-growth operational lane.

## Summary

- Adds connector-safe verified legal-entity records for four existing catalog vendors: Palantir, Paychex, SAP, and Shopify.
- Adds one SEC EDGAR public-authority source for each selected legal entity.
- Uses existing vendor-published public sources as the second corroborating source for each entity record.
- Records the connector-mode source list and skip ledger under `maintenance/generated/**`.

## Boundary

- No new vendors.
- No schema changes.
- No matcher/export changes.
- No governance changes.
- No legal, procurement, risk, audit, KYC, AML, sanctions, suitability, or universal-contracting-party conclusions.

## Connector-mode note

Codespaces/local execution was unavailable for this batch. To avoid hand-editing derived outputs, this PR intentionally does not update `indexes/**`, `dist/**`, or `openva-pack.json`. Those generated outputs should be produced by the canonical repository toolchain before merge if the checks require committed generated artifacts.

## Validation

Not run locally in this connector-only path. Expected repository validation path:

```bash
python -m tools.openva.validate build-indexes
python -m tools.openva.source_verification verify \
  --source-path-file maintenance/generated/pr583-new-sources.txt \
  --output /tmp/pr583-source-verification-report.json
python -m tools.openva.observation_ledger build \
  --verification-report /tmp/pr583-source-verification-report.json \
  --output-dir /tmp/pr583-observations \
  --baseline maintenance/source-observations/latest-observations.json \
  --run-id pr583-connector-verified-legal-entity-backfill-2
python -m tools.openva.observation_ledger install-latest \
  --latest /tmp/pr583-observations/latest-observations.json
python -m tools.openva.release_gates check --profile pr
python -m tools.openva.validate validate
```
