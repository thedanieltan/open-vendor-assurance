# Coverage Growth Engine

OpenVA grows the catalog by category priority, source completeness, confidence, and freshness — not by raw URL count. The coverage growth engine identifies missing vendors, missing source types, stale sources, and high-priority categories, and routes all growth through the candidate/submission/verification model.

It is reporting and prioritization only. It performs no crawling, no scraping behind bot protection, no mass vendor dumps, no direct catalog writes, no compliance scoring, and it uses no paid or private vendor datasets. New vendors enter as candidates; catalog data changes only through reviewed pull requests. Coverage completeness is an operational metric, never a statement that a vendor is approved, compliant, suitable, or any risk level.

## The coverage target model

`config/coverage-targets.yaml` is a growth-reporting overlay on the controlled vendor-category taxonomy (`config/category-taxonomy.yaml`). It defines:

- **priority coverage categories**, each mapping to one or more existing taxonomy tags (vendor records are never edited for growth reporting);
- **category weights** — high-priority categories are exactly those with `weight >= 5`;
- **required source types**: `trust_center`, `dpa`, `subprocessors_list`, `privacy_notice`, `security_page`, `status_page`;
- **source-type criticality**, **staleness weights**, and the **prevalence weight**;
- **priority_vendors wishlists** per category — maintainer-curated public vendor names (seeded from `docs/vendor-expansion-backlog.md`), matched to the catalog by `vendor_id`, updated only through reviewed PRs.

All weights are editorial. Every queue row records its additive score breakdown, so any ranking is auditable, and nothing consumes the priority automatically.

## Priority formula

```text
priority = category weight
         + missing source criticality   (source_type_criticality; 0 when not applicable)
         + business prevalence          (prevalence_weight when the vendor is on a wishlist)
         + staleness component          (staleness_weights by freshness status)
```

Worked example: a wishlist vendor in the `cloud` category (weight 5) whose `dpa` source (criticality 3) reads `stale` (staleness 2) scores `5 + 3 + 2 + 2 = 12`. Ties break deterministically by queue class, category, vendor_id, then source_id.

## Queue classes

```text
missing_vendor                    wishlist vendor not materialized
missing_source_type               materialized vendor missing a required source type
stale_source                      source freshness stale/expired/unknown (high-priority-category vendors)
ambiguous_source                  canonical_confidence.class is ambiguous, or latest observed health is gated/bot_protected
high_priority_vendor              vendor in a weight>=5 category with incomplete required source types
machine_readable_surface_needed   required-type source without a recorded machine-readable surface (priority categories)
```

Every queue row carries `route: candidate_submission` — the next step is always a submission-form claim or a discovery candidate, never a direct write.

## Reports

`python -m tools.openva.coverage_growth build` produces one JSON report (plus a maintainer markdown summary and a CSV queue export) with these sections: vendor count by category, source completeness by category, missing DPA sources, missing subprocessor sources, missing trust centers, stale high-priority sources, candidate backlog by category, top missing vendors, machine-readable source coverage, and the prioritized growth queue. The report is generated weekly by `coverage-audit.yml` as a read-only artifact, for maintainers and agents alike.

## Freshness inputs and honest degradation

Staleness uses the latest source-maintenance run artifact (`observation-ledger/latest-observations.json` and `source-freshness-report.json`) when available. The report's `observation_input` field records which input class built it:

```text
run_artifact               freshness from the latest maintenance run (authoritative)
committed_events_fallback  the committed change-event ledger (sparse: events only) — explicitly marked
none                       no observation input; freshness reads unknown
```

`unknown` freshness contributes a small nonzero staleness weight so never-observed priority sources surface rather than hide.

## Wishlist curation

Wishlists contain public vendor names only, in modest per-category lists. Add or remove entries through reviewed PRs against `config/coverage-targets.yaml`; keep entries aligned with `docs/vendor-expansion-backlog.md`. A wishlist entry is a curation signal, not a commitment — a vendor is added only when a suitable public vendor-controlled source exists and the record can stay metadata-only, public-source-only, and non-advisory.

## Non-advisory reminder

Coverage counts, completeness ratios, priorities, and queue positions describe the state of OpenVA's public-source catalog. They never mean a vendor is approved, recommended, certified, compliant, safe, adequate, suitable, low risk, or high risk.
