# Legal-entity export ratification (WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01)

**Status:** Pending independent acceptance. Independent review found two genuine
functional defects in the bundled legal-entity change set; both were corrected in
PR #403 and are now locked by adversarial/parity/regression tests. This record is
non-authoritative narrative and a recommendation only — it is **not** an acceptance
verdict. The executable evidence is `tests/test_legal_entity_export_ratification.py`;
the governance authority is a maintainer merge after independent review (see the
authority ladder below).

## Authority ladder (what each layer can and cannot decide)

These four layers are deliberately distinct. Only the last one is governance authority.

1. **Implementation + test evidence** — the corrected code and the cited tests
   (`tests/test_legal_entity_export_ratification.py`). This is *executable* and
   independently re-runnable, but passing tests are **not** governance authority: they
   prove the asserted properties hold, not that the change set is accepted.
2. **PR author's recommendation** — this document. A reasoned recommendation that the
   corrected functionality is fit to ratify. It carries no decision power.
3. **Independent review** — a reviewer other than the author examining the change set,
   evidence, and corrections. Advisory input to the maintainer; not the final decision.
4. **Maintainer acceptance** — a maintainer merging the PR after independent review.
   This is the **only** governance authority that ratifies the change set. Until that
   merge, the status is *pending independent acceptance*.

## Why this exists

The legal-entity export + matching enhancement reached `main` **merged but
unratified**. PR #400 (candidate-activation) was branched on top of an in-flight
legal-entity commit (`26b2922`), so its **squash** merge bundled the legal-entity
change set into the candidate-activation work package — it landed without independent
review of *that* change set. This record reconstructs the bundled change set, documents
the defects independent review found, the corrections made in PR #403, and the
regression locks; a [scope guard](pr-scope-guard.md) is added so the mechanism cannot
recur.

## Reconstructed change set (16 files, == commit `26b2922`, verified byte-identical in `main`)

- **Matching authority:** `core.select_with_legal_fallback` (single registration /
  legal-entity fallback authority); `matcher.enrich_row` refactored to use it (pack
  surface); `enrichment.match_identity` uses it with optional legal indexes (snapshot
  surface).
- **MCP surface:** `openva_mcp/matching.py` (`build_legal_indexes`, `match_row` legal
  args), `tools.py` (legal indexes built only when a row carries a registration
  number), `server.py` (tool descriptions / row-schema disclosure).
- **Agent export:** `agent_export.py` (`legal_entity_projection`, optional
  `vendor_export.legal_entities`, emitted only when present);
  `schemas/openva/agent-export.schema.json` (optional `legal_entities` + `legal_entity`
  def); `schemas/openva/agent-enrichment-row.schema.json` (registration disclosure).
- **Docs:** `ADR-0003`, `agent-workspace-composition.md`.
- **Tests:** `test_agent_export.py`, `test_matching_conformance.py`,
  `test_openva_enrichment_parity.py`, `test_openva_mcp_enrich.py`,
  `test_openva_mcp_protocol.py`.

## Defects found by independent review (both corrected in PR #403)

The retrospective audit initially recorded the bundled change set as defect-free. The
**first independent review (NOT_READY)** then identified — and the subsequent
investigation confirmed — **two genuine functional defects** in the bundled
functionality. Both are corrected in PR #403, in the shared
`core.select_with_legal_fallback` and the agent exporter respectively, so the pack,
snapshot and MCP surfaces all behave consistently:

1. **Conflicting vendor identity vs. registration evidence (cross-link).** When
   domain/name evidence selected vendor A but the registration resolved to vendor B's
   legal entity, the matcher could attribute the result to A or cross-link A to B's
   legal entity. **Correction:** `core.select_with_legal_fallback` now **fails closed**
   on this conflict — it attributes to neither vendor and cross-links nothing
   (`registration_vendor_conflict`).
2. **Unverified legal-entity stubs exported as public-source-backed data.** The exporter
   could project unverified legal-entity stubs while the export claimed
   public-source-backed data. **Correction:** the exporter now projects **only**
   verified/canonical legal entities — which carry verification source ids by schema
   invariant — and excludes unverified stubs.

Adversarial, parity, and regression tests now lock the corrected behaviour (cited in
the table below). The remaining ratification decision is **pending independent
acceptance** per the authority ladder above.

## Audit findings (post-correction)

All verified against the corrected code on this PR head; the executable evidence is the
cited tests. The verdicts below describe the **corrected** behaviour and the locks that
hold it — they are property checks, not a ratification decision.

| # | Property | Status (corrected behaviour) | Evidence |
| --- | --- | --- | --- |
| 1 | Registration fallback creates no false-positive matches | Holds after correction | Empty / whitespace / unknown registration → no match; AND conflicting strong identity (domain/name → A, registration → B) now fails closed instead of attributing to A or cross-linking B (defect 1 correction); `test_no_false_positive_on_empty_or_unknown_registration`, `test_conflicting_domain_and_registration_fails_closed_in_core`, `test_conflicting_evidence_is_not_a_match_on_the_mcp_surface` |
| 2 | Ambiguous registration fails closed | Holds | Two vendors sharing a registration → `no_match` (resolution `ambiguous`, no vendor selected); `test_ambiguous_registration_fails_closed_and_jurisdiction_disambiguates` |
| 3 | Jurisdiction handling is deterministic | Holds | Snapshot rows carry no jurisdiction → ambiguous-without-jurisdiction conservatively fails closed; a supplied jurisdiction deterministically disambiguates; same test |
| 4 | Pack / snapshot / MCP / agent-export behaviourally consistent | Holds | Both surfaces call the SAME `core.select_with_legal_fallback` (not a fork), so the defect-1 correction applies uniformly; `test_snapshot_and_pack_share_one_registration_authority`, `test_matching_conformance`, `test_openva_enrichment_parity` |
| 5 | Vendors without legal entities stay backward-compatible | Holds | The optional `legal_entities` key is emitted only when present, so the shipped catalogue (no legal entities) is byte-identical; `test_vendor_without_legal_entities_is_backward_compatible` |
| 6 | Optional export fields comply with the versioning policy | Holds | Additive optional field within `0.1.x` (versioning-policy §"Backward-compatible optional field additions"); consumers safely ignore it; `schema_version` unchanged |
| 7 | Exported legal-entity metadata is verified/public-source-backed and non-advisory | Holds after correction | Only VERIFIED (canonical) entities — which carry verification source ids by schema invariant — are exported; unverified stubs are excluded (defect 2 correction). The exported record is valid under the RAW legal-entity schema, and a legal-entity-bearing export passes the leakage/advisory/non-advisory/digest gates; `test_exported_entity_is_valid_under_the_raw_legal_entity_schema`, `test_unverified_stub_entities_are_not_exported`, `test_legal_entity_export_passes_all_release_gate_scanners` |
| 8 | No new catalogue mutation or authority path | Holds | Read-only projection + matching; MCP tool surface unchanged (no write tool); no `data/**` mutation, no automerge/authority coupling; `test_legal_entity_enhancement_added_no_write_tool_or_authority` |
| 9 | Generated artifacts and schemas remain deterministic | Holds | `legal_entities` sorted by `entity_id`; build-twice byte-identical; `test_legal_entity_export_is_build_twice_deterministic`; no `build-indexes` drift |

### Notes (characteristics, not defects)

- **Registration normalisation** (`core.normalize_registration_number`) strips all
  non-alphanumerics and upper-cases, so `RC-555123` / `rc555123` / `RC 555123` collide
  intentionally. This is the **pre-existing** pack-matcher behaviour, now applied
  consistently on the snapshot surface; it is not introduced by this change set.
- **Jurisdiction parity boundary:** the host-neutral row has no jurisdiction field, so
  a registration that is ambiguous without a jurisdiction is `no_match` on the snapshot
  while the pack (given a jurisdiction) can disambiguate. This is fail-closed and
  intentional — the surfaces converge whenever jurisdiction is not required.

## Independent review remediation (#403)

The first independent review of this ratification PR (NOT_READY) found the two genuine
correctness defects above in the bundled functionality, plus two guard-enforcement
gaps. All were addressed on a new head:

1. **Scope guard not enforced (finding 1).** Added a `pr-scope-guard` job to the core
   `validate.yml` workflow (registered in `.github/validation-ownership.yaml` as the
   required `validate / pr-scope-guard` status context) — a PR-only check that derives
   exactly one `Work-Package: WP-...` declaration from the PR body (fails closed on
   zero/multiple/unknown) and runs the guard against the exact base→head diff. It is a
   job on the existing workflow rather than a new top-level workflow file, so it does not
   perturb the workflow-surface governance contracts (inventory, operating-model,
   retirement evidence, calibration).
2. **Conflicting-identity false attribution (defect 1).** `select_with_legal_fallback`
   now fails closed when domain/name selects vendor A but the registration resolves to
   vendor B's entity — it attributes to neither and cross-links nothing
   (`registration_vendor_conflict`). Corrected once in the shared core, so the pack,
   snapshot and MCP surfaces all behave consistently.
3. **Public-source provenance (defect 2).** The exporter now projects only VERIFIED
   (canonical) legal entities — which carry verification source ids by schema invariant —
   and excludes unverified stubs; the audit fixture is a valid canonical record under the
   RAW legal-entity schema.
4. **Guard self-authorization (finding 4).** The CI guard evaluates the manifest AND the
   guard code from the **trusted base revision**, so a PR cannot weaken its own gate or
   expand its own allowlist in the same change; policy changes take effect only after they
   merge (and are human-reviewed). Because the guard skips when the base lacks it
   (self-bootstrap), this introducing PR's scope-guard success may be bootstrap-only and
   is not by itself proof the diff satisfies the future policy.
5. **Stale doctrine (non-blocking).** Reconciled the `openva_mcp/matching.py` module
   docstring, which previously claimed the snapshot carries no legal-entity data.

## Recommendation (not a verdict)

The retrospective audit initially identified — and independent review subsequently
confirmed — **two substantive functional defects** in the bundled legal-entity change
set: (1) conflicting vendor identity vs. registration evidence could cross-link one
vendor to another vendor's legal entity, and (2) unverified legal-entity stubs could be
exported while the export claimed public-source-backed data. **Both were corrected in
PR #403** (conflict fail-closed in the shared `core.select_with_legal_fallback`;
verified/canonical-only export), and adversarial + parity + regression tests now lock
the corrected behaviour. The scope guard is enforced in CI from a trusted base.

On that evidence, the legal-entity functionality is **RECOMMENDED for ratification
after independent review and a maintainer merge**. This is a recommendation, not a
verdict: the ratification decision is **pending independent acceptance**, and only a
maintainer merge after independent review constitutes that acceptance. This PR is opened
for that review and is not merged autonomously.
