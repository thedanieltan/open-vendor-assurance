# ADR-0003: Machine-enforced discovery/canonical plane boundary

Status: **Proposed** (implemented + locally verified on `refactor/openva-data-plane-boundary`; not deployed; not live-accepted).
Work package: WP-OPENVA-DATA-PLANE-BOUNDARY-01.

## Context
The four-plane model separates the **discovery data plane** (rich candidate records: raw
signals, verification attempts, evidence) from the **canonical catalog plane** (`data/vendors/**`
— lean, mutable, latest-branch = truth, no versioning). The headline objective is that GitHub
stays the governance/publication control plane but is **not** the bulk transport for raw
discovery candidates.

Today the discovery plane physically lives inside the canonical Git tree: 1,416
`data/vendors/*/candidate_sources/*.yaml` files across 500 vendors, plus a ~2.4 MB generated
`indexes/candidate-sources.json`. Relocating that bulk into an external append-only store
(SQLite/artifacts/R2) is the eventual move, but it is infrastructure-gated and high blast radius.
Two preconditions must hold before any relocation is safe, and must not silently erode in the
meantime:

1. the discovery plane must be **addressable by a deterministic, content-derived identity** (so
   records can live in a store keyed by that identity rather than by a Git path); and
2. the canonical plane must stay **disjoint** from discovery bulk (so a canonical write never
   becomes a bulk-transport path again).

## Decision
Add `tools/openva/data_plane_boundary.py`, a fail-closed guard wired into
`tools.openva.validate.validate_all` as `check_data_plane_boundary`, enforcing both invariants:

1. **Store-addressability.** Every committed candidate record must reproduce its own
   `candidate_source_id` from `candidate_source_id(vendor_id, source_type_candidate,
   canonical_candidate_url)` — the same deterministic function the discovery pipeline uses. All
   1,416 committed records reproduce exactly (0 mismatches, 0 missing canonical URLs), so the
   plane is provably store-ready.
2. **Plane disjointness.** The canonical `source-reference` schema must keep
   `additionalProperties: false` and must never declare any discovery-plane-only bulk field
   (`evidence`, `discovery_method`, `requires_review`, `candidate_status`, `candidate_url`,
   `evidence_digest`, `superseded_by_candidate_id`, …). If one appears there, the guard fails.

## Consequences
- Additive and backward-compatible: **no files are moved and no workflow is removed.** The guard
  asserts the current state and locks the boundary against erosion.
- It is the safe precondition for the physical relocation increment: once the store exists, the
  discovery writers target it and the in-tree `candidate_sources/*.yaml` files (and their
  generated index) are removed under a documented migration + rollback — a separate,
  infrastructure-gated work package, not this one.
- No matching, provenance, fail-closed, or public-source-only behaviour changes.

## Alternatives considered
- Physically migrate the 1,416 records now: rejected for this increment — high blast radius, needs
  external store infrastructure, and touches the live discovery/promotion workflows. Enforcing the
  boundary first de-risks that move.
- Enforce only in the discovery generator: rejected — the invariant must hold for the committed
  corpus (what a store would ingest) and for the canonical schema, independent of any single
  generator run; `validate_all` is where the whole-tree invariants live.
