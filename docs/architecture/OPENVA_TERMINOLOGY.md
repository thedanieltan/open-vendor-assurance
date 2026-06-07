# OpenVA terminology

OpenVA is a GitOps evidence registry: a public-source-only, metadata-first, consumer-neutral registry of vendor-published assurance references. It records source locations and evidence metadata; it is not a risk scoring product, compliance advice product, or SaaS compliance platform.

This document is the repository terminology guide for AI agents and maintainers. It is derived from `docs/architecture/OPENVA_SYSTEM_DESIGN.md`, which remains the architecture authority. The purpose of this guide is to prevent semantic drift when natural-language prompts, issues, reviews, and operator comments use informal or imprecise wording.

Humans may provide context in non-canonical language. Agents must normalize that context into the terms below before changing code, schemas, workflows, tests, generated PR bodies, operator-facing docs, or machine-readable contracts. Do not copy informal prompt wording into repository artifacts when a canonical term exists.

## Agent normalization rule

Before implementation, translate human-provided phrasing into repo-authoritative terminology. If the phrase is ambiguous, infer the safest term from the file being changed and the write path involved. Preserve deprecated terms only at explicit compatibility boundaries.

| Human may say | Agent should implement as |
|---|---|
| plan cap | `max_promotion_actions_per_pr` when referring to the generated Catalog PR selected-action cap |
| max actions per plan | deprecated alias only; prefer `max_promotion_actions_per_pr` |
| auto-merge strict-growth-latest | `strict-growth-latest` generation plus the separate `automerge:strict-growth` lane |
| strict-growth auto-applies | candidate-promotion opens a PR; `agent-automerge` may enable native GitHub auto-merge after guards pass |
| source count / source depth | source-role coverage or `coverage_claims`, unless literally counting canonical source records |
| candidate queue | candidate backlog, candidate source discovery queue, or discovery queue depending on context |
| catalog truth | canonical catalog state |
| source health preflight | source preflight if blocking changed canonical source records; source health if reporting longitudinal posture |
| agent pipeline | workflow, controlled write path, or automerge lane depending on context |
| scraped database | public-source-only metadata registry |
| vendor-risk record | canonical vendor/source metadata or downstream consumer risk record, depending on repo boundary |

## Product identity

- **GitOps evidence registry**: repository-governed registry where catalog changes, evidence, generated outputs, and publication outputs are reviewable through Git history and workflows.
- **Public-source-only metadata registry**: OpenVA records public page and document locations plus metadata. It does not mirror raw documents by default.
- **Consumer-neutral evidence registry**: OpenVA records public evidence references without turning them into vendor-risk advice, recommendations, or scores.

## Repository layers

- **Canonical catalog** / **canonical catalog state**: durable vendor, source, artifact, and change records under `data/vendors/**`.
- **Canonical vendor**: vendor identity record promoted into canonical catalog state.
- **Canonical source record**: promoted source metadata record for a public page or document location.
- **Canonical artifact reference**: promoted metadata-only artifact reference linked to a canonical source record.
- **Staging / candidate layer**: candidate vendors, candidate sources, discovery outputs, backlog material, and review-required material that propose but do not by themselves mutate canonical catalog state.
- **Review evidence**: human-reviewed or machine-reviewed evidence that supports a controlled promotion or repair path.
- **Source maintenance**: operational review and repair material for existing source records, including source verification reports and source-health posture outputs.
- **Generated exports**: generated indexes, distribution bundles, and pack files under `indexes/**`, `dist/**`, and `openva-pack.json`.
- **Publication layer**: site/publication material under `site/**`.

## Source model

- **Source record**: a public page or document location recorded as metadata.
- **Source location**: the public URL location represented by `source_url`.
- **source_url**: canonical public source location stored on a canonical source record.
- **source_type**: primary classification of a source location.
- **Source role**: assurance, legal, privacy, security, or other role covered by a source location.
- **Coverage claim**: explicit source-role coverage evidenced by a source record, usually represented as `coverage_claims`.

One URL should normally produce one canonical source record. One canonical source record may carry multiple explicit coverage claims. Source count is not a proxy for full source-role coverage.

## Candidate and promotion model

- **Candidate vendor**: discovered vendor candidate that is not canonical catalog state until promoted.
- **Candidate source**: discovered source candidate that is not a canonical source record until promoted.
- **Candidate source discovery**: discovery that proposes candidate source locations.
- **Candidate backlog**: candidate material retained for later review or future promotion.
- **Strict-growth candidate**: candidate that may qualify for strict-growth promotion if all eligibility and guard checks pass.
- **Review-required candidate**: candidate that requires human review before promotion.
- **Deferred candidate**: candidate or promotion action held back by caps, source-health screening, redirect cleanliness, or other guardrails.
- **Rejected candidate**: candidate that failed eligibility or policy checks.
- **Strict-growth eligibility**: classification that determines whether a candidate is eligible for strict-growth promotion planning.
- **Strict-growth promotion plan**: evidence-bearing object with selected actions, deferred actions, source-health and redirect evidence, policy caps, and metadata.
- **Selected promotion action**: promotion action selected to be applied by a generated Catalog PR.
- **Deferred action**: eligible or discovered action not applied by the generated Catalog PR.
- **Batch-deferred action**: action deferred only because the generated-PR promotion-action cap was reached.
- **max_promotion_actions_per_pr**: maximum selected promotion actions applied by one generated Catalog PR.

Discovery proposes. Promotion writes. Canonical catalog changes happen only through controlled write paths.

## Strict-growth and automerge

- **strict-growth-latest**: generation mode that selects the latest strict-growth eligible promotions. It generates candidate-promotion evidence and a promotion plan; it does not merge by itself.
- **automerge:strict-growth**: explicit automerge label/lane for strict-growth Catalog PRs.
- **machine-canonical**: automerge lane for machine-canonical catalog changes that pass the configured policy and guards.
- **P0 source repair**: automerge lane for confirmed P0 source repair changes, with independent evidence and freshness checks.

Candidate-promotion workflows open PRs. The agent-automerge workflow enables native GitHub auto-merge only after labels, policy, evidence, and guard checks pass.

## Source quality terminology

- **Source verification**: network/source observation and classification. It records availability, redirects, HTTP status, and semantic observations.
- **Source preflight**: blocking check over changed canonical source records, especially before a generated Catalog PR is accepted.
- **Source health**: broader longitudinal operating posture over source availability, quality, redirects, and maintenance debt.
- **Redirect canonicalization**: storing a safe final URL as `source_url` when redirect evidence supports canonicalization.
- **Redirect-clean**: selected strict-growth actions have no unresolved redirects or unsafe redirect decisions.

A redirected source may be alive, but unresolved redirect evidence is not strict-clean for new strict-growth records.

## Deprecated / compatibility terms

- **max_actions_per_plan**: deprecated alias. It actually caps selected promotion actions per generated PR, not the full promotion plan. Use `max_promotion_actions_per_pr` for new operator-facing inputs, summaries, tests, and prompts. The legacy name may remain only at compatibility boundaries, compatibility tests, legacy fixtures, or deprecated-alias documentation.
