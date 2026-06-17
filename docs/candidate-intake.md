# Candidate intake

How a staged candidate record reaches the autonomous catalogue-growth lifecycle.
Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.

## The pipeline

```text
unified resolver ──▶ CatalogQueueIngress ──▶ maintenance/candidates/<id>.json
(vendor_resolution.py)  (canonical writer)        (non-canonical staging)
                                                         │ candidate-intake PR
                                                         ▼
                                 automerge:candidate-intake lane + guard
                                                         │ controlled merge to main
                                                         ▼
                             autonomous-catalog-growth.yml (decide_cycle gate;
                                              scheduled / workflow_dispatch only)
                                                         │ one eligible candidate
                                                         ▼
                             candidate-promotion-pr.yml (independent quorum)
                                                         ▼
                                      catalogue truth (data/vendors/**)
```

The candidate store `maintenance/candidates/*.json` is **non-canonical staging**,
written by the unified resolver's durable ingress
(`vendor_resolution.CatalogQueueIngress` — the single canonical writer, already on
`main`: atomic, locked, idempotent merge, honest durability ladder). Merging a
candidate-intake PR does not write catalogue truth and does not decide promotion —
promotion still flows through the independent quorum/promotion path. Separation of
duties is intact: the resolver *discovers*; independent components *decide and
merge*.

## What this adds (over the merged resolver/ingress)

| Piece | Where |
| --- | --- |
| Path-scoped automerge lane | `automerge:candidate-intake` in `config/automerge-policy.yaml` + `tools/openva/automerge_lanes.py` (`is_candidate_intake_path`, single-level `maintenance/candidates/*.json`, **no generated/canonical escape hatch**), `execution_wired: false` until the consuming job lands |
| Admission guard | `tools/openva/candidate_intake_guard.py` — path confinement, no canonical/generated drift, schema validity. It does **not** re-derive eligibility (see Deferred) |

These are additive and inert: `main` has no candidate-intake automerge lane or
guard. This spine deliberately does **not** add an event-driven trigger. The
autonomous growth controller already globs `maintenance/candidates/*.json` and
selects records by their committed `eligibility_state` on its existing
schedule/dispatch; a `push`-triggered fast path must not be wired until the
consuming job recomputes eligibility and binds candidate identity end-to-end (see
Deferred). With `execution_wired: false`, no candidate-intake PR auto-merges, so
nothing reaches `main` through this path yet.

## Deferred (follow-up, lands with the consuming job)

- **Event-driven freshness trigger — only with the candidate-bound consuming
  path.** A `push` trigger on `maintenance/candidates/*.json` would let the growth
  controller consider a newly-merged candidate promptly rather than only on its
  schedule. It is intentionally **not** added in this spine: an event-driven
  trigger must not be activated while its input is merely a gate signal. It lands
  together with a consuming path that (a) **recomputes** eligibility from each
  persisted record via the resolver's own evaluation — never trusting the
  self-declared `eligibility_state` — failing closed on any mismatch, and
  (b) **binds candidate identity** (candidate_id / path / digest / origin /
  selected vendor) through to the downstream promotion mutation, so the promotion
  job consumes the candidate record rather than re-deriving the vendor from a
  separate queue.
- **Eligibility reproducibility in the guard.** The guard does not re-derive the
  committed `eligibility_state`. Re-deriving the resolver's per-origin eligibility
  in this side module would be a second evaluator; that admission check belongs in
  the consuming agent-automerge job, where it can call the resolver's own
  evaluation path.
- **The consuming agent-automerge candidate-intake job + the PR-open workflow** —
  both need a GitHub App / `OPENVA_AUTOMERGE_TOKEN` and branch protection (the
  external boundary). The job runs `python -m tools.openva.candidate_intake_guard`
  plus the release gate, checks out the PR head, then enables native auto-merge. A
  PR opened with the default `GITHUB_TOKEN` does not trigger downstream workflows,
  so it must use an App installation token (mirror
  `observation-ledger-append-pr.yml`).
- **Scheduled sitemap-discovery → ingress convergence.** Scheduled discovery is
  still report-only; converting `sitemap_source_discovery_events` into the unified
  candidate queue must hand records to `CatalogQueueIngress`, not a parallel writer.
- **`bot-authority.yaml` lane entry** — declare a `candidate_intake` lane
  (`authority_level: 1`, `may_write_catalog_truth: false`, `may_merge_prs: false`,
  `deny_by_default: true`, `workflows: [agent-automerge.yml]`) once the consuming
  job exists, so it never references a not-yet-present workflow.

Until the consuming job is wired, the lane (`execution_wired: false`) and guard are
inert and exercised offline against committed fixtures.
