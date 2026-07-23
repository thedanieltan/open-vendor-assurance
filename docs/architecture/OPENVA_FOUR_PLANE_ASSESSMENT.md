# OpenVA Four-Plane Refactor — Phase 0 Assessment & Plan

Status: **assessment complete; implementation in progress (increment 1).**
Branch: `refactor/openva-four-planes`. Base: `main` @ `48a71c33`.

This document is the Phase 0 deliverable required before code changes: a current-state
map, identified problems (verified against `main`, not inherited from prior assessments),
a revised implementation plan, and the target architecture. It supersedes any earlier
informal assessment.

---

## 1. Current-state map (verified on `main` @ 48a71c33)

| Concern | Where it lives today | Notes |
|---|---|---|
| Browser runtime | `site/src/app.js` + late-patch stack (`ui-fixes.js`, `catalog-navigation.js`, `catalog-card-interactions.js`, `catalog-donor-alignment.js`, `public-vendor-detail.js`, `resolver-source-availability.js`) | Assembled by `site/build.py` via **string-marker script injection**; behaviour depends on load order |
| Python matcher/resolver | `tools/openva/resolve_csv.py`, `resolver_result_pack.py`, `vendor_resolution.py`, `source_authority.py` | The reference matching core |
| Hosted HTTP resolver | `services/openva_match_service/` (Python) | A second matching surface |
| Live resolver (edge) | `infra/cloudflare/openva-live-resolver/worker.js` (JS) | A third matching surface |
| Browser matcher | `site/src/*.js` (patched by `ui-fixes.js`) | A fourth matching surface |
| MCP adapter | `integrations/mcp/openva_mcp/` | Transport over the core |
| CSV export adapter | `adapters/python/openva_csv_export/` | Transport over the core |
| Discovery workflows | `discovery-mesh.yml`, `discovery-mesh-intake-recovery*.yml`, `catalog-growth-discovery.yml`, `rendered-discovery-acceptance-controller.yml`, `source-refinement-*.yml` | Produce raw candidates |
| Candidate storage | `data/vendors/<v>/candidate_sources/*.yaml` (**1,416 raw files in Git**) | Discovery data stored **inside** the canonical tree |
| Promotion workflows | `candidate-promotion-pr.yml` (sole canonical writer), `candidate-intake-pr.yml`, `catalog-growth-promotion-bridge.yml`, `machine-provisional-materialization.yml` | PR-governed |
| Site compiler | `tools/openva/indexes.py`, `site/build.py`, `site/build_core.py` | **Full-catalog rebuild** (`records_for` loads all; iterates every vendor) |
| Generated indexes | `indexes/` (14), `dist/` (500), `openva-pack.json` | Rebuilt wholesale; observed to go stale |
| Publication workflows | `site-pages.yml`, `site-live-feed.yml`, `release-image.yml` | |
| Vocabulary / capabilities | `config/controlled-vocabulary.yaml`, `schemas/openva/vocabularies/`, `SOURCE_TYPE_REGISTRY` (in `source_discovery.py`), `RESULT_PACK_VERSION` (in `resolver_result_pack.py`) | Multiple hand-maintained copies |

Total: **34 workflows**, **159 `tools/openva` modules**, **9,252 tracked files** (7,391 under `data/`).

## 2. Identified problems (evidence, not assumption)

1. **Load-order-dependent browser runtime.** `ui-fixes.js:517–521` reassigns the core matcher
   (`matchInventoryRow`, `normalizeDomain`, `normalizeForMatch`, `parseCsv`,
   `buildLocalMatchIndexes`) at load time; `catalog-navigation.js` and
   `catalog-card-interactions.js` both overwrite `window.renderCatalog`/`renderVendorDetail`.
   `ui-fixes.js:499` removes listeners via `cloneNode(true)` + `replaceWith`. The *real*
   matcher is whichever patch loaded last. `build.py` injects script tags by locating a
   string marker — fragile ordering.
2. **Four independent matching surfaces** (Python core, Python hosted service, JS edge Worker,
   JS browser) with no shared contract or conformance vectors.
3. **Duplicated, already-drifted source-type definitions.** `controlled-vocabulary.yaml` = **15**
   types, `candidate-source.schema.json` enum = **15**, Python `SOURCE_TYPE_REGISTRY` = **9**.
   The registry has already fallen behind the vocabulary — live drift.
4. **Discovery data in canonical Git history.** 1,416 raw `candidate_sources/*.yaml` under
   `data/vendors/`; the discovery→canonical boundary is a naming convention, not a structure.
   This produced the massive-Git-transaction failures the recovery programme has been fighting.
5. **Full-catalog rebuild.** `indexes.py` regenerates all 500 `dist/` shards + 14 indexes on any
   change; outputs observed stale on `main` (generated-output drift).
6. **Validation-by-token-grep.** `build.py._validate_*` assert on source-code substrings rather
   than built behaviour.
7. **Docs vs behaviour drift** (carried, still true): `repository-integrity`/`catalog-quality`
   are not enforced merge gates on the auto-merged partition path (PR #765 merged with both
   red); publication artifacts stale.
8. **Python floor mis-declared.** `requires-python = ">=3.11"` but `site_discovery.py:191`
   uses 3.12-only f-string syntax → local 3.11 builds/tests spuriously fail.

## 3. Revised plan (sequencing + rationale)

The task's WP list is sound. Revision: **sequence by (foundational × low-risk × locally-verifiable)
first**, because several WPs share a dependency on a single source-type/capability definition.

| Order | Work package | Why here | Risk |
|---|---|---|---|
| 1 (this increment) | **WP-CAPABILITY-CONTRACT** | Foundational for runtime + resolver WPs; additive; fully locally verifiable; fixes drift #3 | Low |
| 2 | **WP-RESOLVER-UNIFICATION** | Needs the manifest; produces conformance vectors runtime WP consumes | Med |
| 3 | **WP-RUNTIME-CONSOLIDATION** | Consumes unified core + manifest; headless tests | Med |
| 4 | **WP-DATA-PLANE-SEPARATION** | Headline objective; largest/riskiest; additive-first w/ migration+rollback | High |
| 5 | **WP-INCREMENTAL-COMPILER** | Depends on stable shard identity from the data plane | Med |
| 6 | **WP-WORKFLOW-CONSOLIDATION** | Retire only after replacements proven | Med |
| 7 | **WP-LIVE-RESOLVER-BOUNDARY** | ADR + conformance vs unified core | Low-Med |
| 8 | **WP-DOCUMENTATION-TRUTH** | Last, so docs match the new reality | Low |

Each increment: implement → local validation/tests → commit → honest status. No WP retires a
component until its replacement is proven and a migration + rollback exists.

### Migration & rollback (global)
- All new stores/artifacts are **additive**; the existing Git-backed path stays until parity is proven.
- Every generator ships a `check`/freshness mode that **fails closed** on staleness.
- Rollback = revert the WP commit(s); no data destroyed because canonical mutation stays PR-only.

### Test strategy
- Per-WP unit tests + the full existing suite (Python 3.12 in CI; 3.11 locally skips the 3.12-only site tests).
- Cross-runtime conformance vectors (WP2), incremental-vs-full equivalence (WP5), store idempotency/replay (WP4).
- Freshness/consistency tests that fail when any surface drifts from its generated source.

### Compatibility constraints
- Preserve deterministic IDs, provenance model, non-advisory boundary, PR-only canonical writes,
  fail-closed behaviour, public-source-only boundary.
- No arbitrary catalog/candidate/action caps.

## 4. Target architecture (four planes)

```
                ┌──────────────────────── GOVERNANCE & PROMOTION PLANE ───────────────────────┐
                │  GitHub = control plane: PR-only canonical writes, scope guard, weighted     │
                │  review, required gates, deterministic recovery, capability manifest          │
                └───────▲───────────────────────────────────────────────────────▲─────────────┘
                        │ compact, qualified, signed promotion manifests           │ gates
   DISCOVERY DATA PLANE │ (NOT bulk raw candidates)                                │
   append-only intermediate store (SQLite/DuckDB/artifacts/R2)   ── promotion ──►  CANONICAL CATALOG PLANE
   raw signals, candidates, verification attempts, receipts       projection       data/vendors/** (lean, mutable,
   deterministic id = hash(identity+type+url+rule_version)                          latest-branch = truth, no versioning)
                                                                                          │
                                                                                          ▼
                                                                            DELIVERY PLANE
                                              incremental compiler → shards+indexes → site / exports /
                                              live resolver (cache-miss/unknown vendors only)
```

Authoritative matching **core** (one implementation + generated contracts) sits under the
governance plane and is consumed by every transport (browser, MCP, Worker, CSV, hosted HTTP).
The **capability manifest** (WP1) is the single generated source for source types, aliases,
per-transport availability, and contract versions.

---

## Increment log
- **1 — WP-CAPABILITY-CONTRACT**: see commit(s) on this branch + `docs/architecture/adr/`.
