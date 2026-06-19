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
| Path-scoped automerge lane | `automerge:candidate-intake` in `config/automerge-policy.yaml` + `tools/openva/automerge_lanes.py` (`is_candidate_intake_path`, single-level `maintenance/candidates/*.json`, **no generated/canonical escape hatch**), `execution_wired: true` |
| Admission guard | `tools/openva/candidate_intake_guard.py` — path confinement, no canonical/generated drift, schema validity |
| Persisted-candidate evaluation | `tools/openva/vendor_resolution.py` `evaluate_persisted_candidate` — recomputes eligibility + the deterministic id/evidence digest via the **one** canonical evaluator; fails closed on any mismatch |
| Candidate-bound activation | `tools/openva/candidate_activation.py` — `collect-eligible`, `verify-intake`, `verify`, and `materialize` (identity binding + the candidate-bound mutation, reusing the canonical decision/source/artifact/change writers) |
| Producer (external boundary) | `.github/workflows/candidate-intake-pr.yml` — stages via the canonical ingress and opens the candidate-intake PR with `OPENVA_AUTOMERGE_TOKEN` so the lane triggers |
| Consuming merge job | `agent-automerge.yml` `candidate-intake` job — checks out the PR head, runs the guard, **recomputes** eligibility/identity, runs the release gate, then enables native auto-merge |

> **Candidate intake is wired now that the complete control path is operational.**
> The producer PR-open workflow and the consuming agent-automerge candidate-intake
> job both exist, so `execution_wired: true` and the `candidate_intake`
> bot-authority lane is declared.

## The wired control path (WP-OPENVA-CANDIDATE-ACTIVATION-01)

```text
remote candidate intake (candidate-intake-pr.yml, OPENVA_AUTOMERGE_TOKEN)
  → agent-automerge candidate-intake job
      guard + recompute eligibility/identity (never trust eligibility_state)
      + release gate → native auto-merge (staging record reaches main)
  → autonomous-catalog-growth.yml (push on maintenance/candidates/*.json OR schedule)
      decide_cycle gate → recompute eligibility from the persisted record
      + bind candidate_id / candidate_path / content_digest / origin / selected_vendor
  → candidate-bound promotion dispatch (candidate-promotion-pr.yml, mode candidate-bound)
      verify the binding on the exact head (fail closed) → materialize ONE
      machine_provisional vendor + append-only decision (candidate_digest = content_digest)
  → catalogue PR (machine_provisional; independent quorum + machine-provisional policy govern the merge)
```

Key properties:

- **Candidate records remain non-canonical.** The candidate store
  (`maintenance/candidates/*.json`) is staging; merging a candidate-intake PR does
  not write catalogue truth (`data/vendors/**`) and does not decide promotion.
- **Selected candidate identity and digest are bound through all stages.** The
  controller decision carries `candidate_id`, `candidate_path`, `content_digest`,
  `origin`, and `selected_vendor`; the mutation re-verifies them on the exact head
  and asserts the materialized vendor equals the selected vendor. Identity is never
  re-derived later from a separate queue.
- **Stale or changed records fail closed.** A changed candidate, forged
  `eligibility_state`, altered content/digest, missing record, path substitution,
  id/vendor/origin mismatch, or a head differing from the reviewed candidate state
  all fail the binding closed and create no canonical catalogue PR.
- **Catalogue truth still changes only through the established PR path.** The
  candidate-bound mutation writes a NEW `machine_provisional` vendor only, linked
  to an append-only decision; promotion to a terminal status remains the
  independent WP37 quorum, and the existing machine-provisional merge policy
  governs the catalogue PR.
- This completes autonomous candidate promotion **up to a reviewable, bound
  catalogue PR**; it is **not** production hosting and does not claim OpenVA's
  hosted `/v1` API or remote MCP is live.

## Still deferred

- **Scheduled sitemap-discovery → ingress convergence.** Scheduled discovery is
  still report-only; converting `sitemap_source_discovery_events` into the unified
  candidate queue must hand records to `CatalogQueueIngress`, not a parallel
  writer. The producer (`candidate-intake-pr.yml`) is the deliberate, bounded,
  request-driven external boundary until that convergence lands.
- **Materialization-complete candidates.** A candidate-bound materialization needs
  the metadata a canonical vendor profile requires (a display name and a valid
  ISO-3166 alpha-2 headquarters country). Eligible candidates that lack it fail the
  materialization closed (defer) rather than fabricating it; enriching the
  resolver/ingress to populate it is follow-up catalogue work.
