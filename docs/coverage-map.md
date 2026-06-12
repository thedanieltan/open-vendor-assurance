# Coverage Map

This document explains where OpenVA coverage state lives, so catalog expansion remains intentional.

This page no longer carries a hand-maintained snapshot. Static vendor and source counts written here went stale as the catalog grew (an earlier revision of this file described a 17-vendor seed catalog); coverage state is now generated, not transcribed.

## Where coverage state lives

```text
config/coverage-targets.yaml        the coverage target model: priority categories,
                                    required source types, weights, and per-category
                                    priority-vendor wishlists
docs/coverage-growth.md             the coverage growth model, priority formula, and
                                    queue-class definitions
coverage-growth-report.json         the live coverage snapshot: vendor count by
                                    category, source completeness, named gap reports,
                                    stale high-priority sources, top missing vendors,
                                    machine-readable coverage, and the prioritized
                                    growth queue — generated weekly by
                                    coverage-audit.yml as a read-only artifact
indexes/source-coverage.json        generated per-vendor source-type coverage index
docs/vendor-expansion-backlog.md    narrative expansion priorities and batch rules
```

To see current coverage, download the `openva-coverage-audit-report` artifact from the latest `coverage-audit` workflow run, or run locally:

```bash
python -m tools.openva.coverage_growth build \
  --output coverage-growth-report.json \
  --markdown-output coverage-growth-summary.md
```

## Expansion rule

Future expansion should prefer small batches of three to five vendors.

Each batch should state:

- the category being expanded;
- why the category matters;
- the source type used;
- whether the batch adds new edge cases;
- whether generated indexes and pack integrity checks pass.

Do not add vendors merely to increase count. Growth is measured by completeness and freshness, not raw URL count, and new vendors enter as candidates through the submission and verification model.

## Non-advisory reminder

Coverage counts and completeness ratios describe the state of OpenVA's public-source catalog. They never mean a vendor is approved, recommended, certified, compliant, safe, adequate, suitable, low risk, or high risk.
