# Source Observation Freshness Continuity

OpenVA source observations have two committed derivative views:

- append-only change events in `maintenance/source-observations/events/`;
- the latest real observation per source in `maintenance/source-observations/latest-observations.json`.

The event ledger records material source-observation changes. It is intentionally sparse:
unchanged sources do not receive fabricated `non_material_change` or health events.

The latest-observation index records the most recent actual observation for each source,
including observations that produced no event. Release freshness gates merge this committed
index with the append-only event baseline and use the newest valid `observed_at` per source.

The index is derivative and rebuildable. It never replaces the event ledger, never rewrites
event history, and never changes source records. A malformed committed latest index fails
closed during release-gate evaluation.

The source-maintenance report produces both the event delta and the latest index from the
same real verification run. The append PR may include new event rows, the latest index, or
both. No new clock is read while applying that PR; timestamps come from the source
verification report produced by the run.
