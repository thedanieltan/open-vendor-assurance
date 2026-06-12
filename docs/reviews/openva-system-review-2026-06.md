# OpenVA System Review — June 2026

Scope: WP29–WP34 (source registry fields, human submission intake, deterministic verification, observation/change ledger, public agent exports, coverage growth engine). This review asks whether the system is useful, coherent, and sustainable — not whether the tests pass. All figures are measured from the repository and the first live runs on 2026-06-12/13.

Operational metadata only. Nothing here is legal, compliance, procurement, audit, or vendor-risk advice.

## Snapshot

```text
Vendors                    164 (all category-tagged)
Source records             610
Source records carrying ANY WP29 registry field (retrieval,
  canonical_confidence, change_detection, source_health)     0
status_page sources        0 (type added 2026-06-13)
Sources observed at least once (committed ledger)            153 of 610 (25%, one shard)
Candidate sources          0
Growth queue               1,037 rows (13 missing vendors, 360 missing source
                           types, 160 stale [all freshness=unknown], 52
                           high-priority depth gaps, 439 machine-readable
                           surfaces needed, 13 ambiguous)
Public agent exports       live, digest-verified, observation_input=run_artifact
```

## 1. External usefulness — can a DPO, consultant, or AI agent use this for a real vendor list?

**Partially, and honestly labeled.** An agent or practitioner can today: resolve ~164 common SaaS/cloud vendors to their public assurance source URLs through JSON only; see source types per vendor; verify snapshot integrity cryptographically; and check observed reachability for the quarter of sources already observed. The inventory-matcher adapters and CSV releases serve the spreadsheet-first user.

What they cannot yet do: rely on confidence/retrieval metadata (unadopted — see Q3); expect health/freshness on three-quarters of sources (observation is one shard in); or expect depth in identity (4 vendors) and security (12). A mid-size company's real vendor list will hit the catalog perhaps half the time on breadth and less on depth. The system never overstates this — nulls mean not-yet-observed — which is the right failure mode.

**Verdict: useful as a lookup-and-verify layer for common vendors; not yet a dependable first stop for a full vendor list.**

## 2. Catalog adequacy — which categories are too thin?

Measured against the WP34 priority targets (a vendor may count in several categories):

```text
developer_tools 54   sme_common_tools 49   ai 25   crm_sales 22
cloud 21   finance_payments 21   hr_payroll 18   security 12   identity 4
outside priority mapping: 31
```

**Identity is the standout gap**: a weight-5 category with 4 vendors, despite identity providers appearing in virtually every real vendor list. Security (12) is thin for the same reason. The 31 vendors outside the priority mapping are correctly tagged with taxonomy categories (healthcare, insurance, logistics, regional) that simply have no growth target yet — a deliberate scoping choice, not a data gap. The 13 missing wishlist vendors (Okta, Auth0, 1Password, OVHcloud, Hetzner, Personio, Mistral AI, …) cluster in exactly the thin categories, so the wishlist mechanism is pointing at the right work.

**Verdict: breadth is respectable in developer/SME tooling, inadequate in identity and security — the two categories assurance reviews care about most.**

## 3. Source depth — improving real source intelligence, or just adding URLs?

This is the review's sharpest finding. The intelligence INFRASTRUCTURE is complete: registry fields, verification, observation, change detection, exports. But **adoption on actual records is zero**: no source record carries `retrieval`, `canonical_confidence`, `source_health`, or a `change_detection` baseline; no `status_page` source exists; `material_change_since_baseline` is null everywhere because no curated baselines exist. The agent exports faithfully serve nulls for all of it.

Today, OpenVA's depth per source is: URL + type + language + access/rights class + (for 25% of sources) one observation. That is better than a URL directory — verification and observation are real — but the WP29 promise (confidence, retrieval hints, change baselines) is schema-only until records are decorated. Without a decoration path, WP29–WP33 risk being plumbing through which nothing flows.

**Verdict: the system is currently adding verified, observed URLs — genuinely more than bare URLs, but the registry-field layer needs a record-decoration effort (even 20–30 tier-1 sources) before "source intelligence" is fully honest.**

## 4. Agent-readiness — consumable without knowing repo internals?

Strong core: a single entry point (`openva-agent-index.json`) with a lockfile-style digest map, stable IDs, schema-pinned shapes, snapshot identity by commit+digest, and a documented verification recipe. The live smoke proved an external party can verify every served file by recomputation.

Gaps, all ergonomic rather than structural: (a) **discovery** — an agent must already know the Pages base URL; nothing at a well-known location (site `llms.txt`, README link block) points to the agent index; (b) the index does not state its own base URL, so relative paths require out-of-band knowledge; (c) export freshness is bound to Pages deploy cadence, detectable but not yet surfaced as a staleness hint; (d) no MCP server (deliberately deferred). None of these block a motivated agent; all of them add friction for a cold-start one.

**Verdict: structurally agent-ready; one small discovery/ergonomics pass short of friction-free.**

## 5. Maintainer burden — actionable queues, or work generation?

The weekly machinery is bounded and self-tending: submissions and verification are event-driven; observation shards rotate automatically; reports are artifacts, not obligations. The risk sits in the growth queue: **1,037 rows is a prioritization surface, not a to-do list**, and must be read that way. Decomposed:

- 439 `machine_readable_surface_needed` — vendor-dependent, mostly not actionable by a maintainer at all; this class is a measurement, not work.
- 360 `missing_source_type` — real but long-horizon; the per-category completeness ratios are the usable view.
- 160 `stale_source` — all `freshness: unknown`, i.e. observation backlog that the weekly shards will clear without human action.
- 13 `missing_vendor` + 13 `ambiguous_source` + the top of 52 `high_priority_vendor` — **this is the actual actionable set: roughly 30–40 items**, well within solo-maintainer capacity at a few per week through the candidate lane.

One process gap: queue rows say `route: candidate_submission`, but nothing yet turns a queue row into a submission/candidate with one action — the maintainer re-types context. Cheap to improve later.

**Verdict: sustainable IF the queue is consumed top-N; the report should be read as "the next 5 things", and a row→submission shortcut would halve the remaining friction.**

## 6. Trust boundary — still non-advisory, public-source-only, provenance-first?

Intact, and structurally enforced rather than asserted: every record, report, export, and bot comment carries `not_advice`/doctrine; advisory vocabulary is regex-swept in CI across forms, comments, reports, and exports; bots hold deny-by-default lanes with no catalog-write authority (verification: one comment + one label; observation: artifacts + reviewed-PR-only ledger appends; growth: reports only); gated sources are recorded as facts and never probed; declared-gated submissions are never fetched; provenance is cryptographic (sample hashes, append-only monthly ledger, commit+digest snapshot identity). The WP31 declared-gated defect was caught by self-audit, failed toward review, and was fixed forward — the failure mode the boundary design intends.

**Verdict: the trust boundary is the system's strongest property. No drift observed; the enforcement is in contracts and tests, not in discipline.**

## Overall assessment

OpenVA is now a coherent public source-intelligence system with an unusually well-enforced trust boundary and genuinely agent-consumable outputs. Its two real deficits are empirical, not architectural: **thin coverage where it matters most (identity/security)** and **zero adoption of the registry-intelligence fields on actual records**. Both are catalog-work deficits that the existing machinery is designed to absorb; neither calls for new engines. The system's own first growth report identified both — which is itself evidence the WP34 layer works.

See `docs/reviews/openva-roadmap-decision-2026-06.md` for the decision this assessment feeds.
