# Legal-entity export ratification (WP-LEGAL-ENTITY-EXPORT-RATIFICATION-01)

**Status:** Ratified — no substantive defect found; no revert. Evidence and
regression locks below; this record is non-authoritative narrative (the executable
authority is `tests/test_legal_entity_export_ratification.py`).

## Why this exists

The legal-entity export + matching enhancement reached `main` **merged but
unratified**. PR #400 (candidate-activation) was branched on top of an in-flight
legal-entity commit (`26b2922`), so its **squash** merge bundled the legal-entity
change set into the candidate-activation work package — it landed without independent
review of *that* change set. This audit reconstructs and ratifies the bundled change
set, and a [scope guard](pr-scope-guard.md) is added so the mechanism cannot recur.

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

## Audit findings

All verified against `main`; the executable evidence is the cited tests.

| # | Property | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Registration fallback creates no false-positive matches | PASS (corrected) | Empty / whitespace / unknown registration → no match; AND conflicting strong identity (domain/name → A, registration → B) now fails closed instead of attributing to A or cross-linking B (review finding 2 correction); `test_no_false_positive_on_empty_or_unknown_registration`, `test_conflicting_domain_and_registration_fails_closed_in_core`, `test_conflicting_evidence_is_not_a_match_on_the_mcp_surface` |
| 2 | Ambiguous registration fails closed | PASS | Two vendors sharing a registration → `no_match` (resolution `ambiguous`, no vendor selected); `test_ambiguous_registration_fails_closed_and_jurisdiction_disambiguates` |
| 3 | Jurisdiction handling is deterministic | PASS | Snapshot rows carry no jurisdiction → ambiguous-without-jurisdiction conservatively fails closed; a supplied jurisdiction deterministically disambiguates; same test |
| 4 | Pack / snapshot / MCP / agent-export behaviourally consistent | PASS | Both surfaces call the SAME `core.select_with_legal_fallback` (not a fork); `test_snapshot_and_pack_share_one_registration_authority`, `test_matching_conformance`, `test_openva_enrichment_parity` |
| 5 | Vendors without legal entities stay backward-compatible | PASS | The optional `legal_entities` key is emitted only when present, so the shipped catalogue (no legal entities) is byte-identical; `test_vendor_without_legal_entities_is_backward_compatible` |
| 6 | Optional export fields comply with the versioning policy | PASS | Additive optional field within `0.1.x` (versioning-policy §"Backward-compatible optional field additions"); consumers safely ignore it; `schema_version` unchanged |
| 7 | Legal-entity metadata is public-source-backed and non-advisory | PASS (corrected) | Only VERIFIED (canonical) entities — which carry verification source ids by schema invariant — are exported; unverified stubs are excluded (review finding 3 correction). The exported record is valid under the RAW legal-entity schema, and a legal-entity-bearing export passes the leakage/advisory/non-advisory/digest gates; `test_exported_entity_is_valid_under_the_raw_legal_entity_schema`, `test_unverified_stub_entities_are_not_exported`, `test_legal_entity_export_passes_all_release_gate_scanners` |
| 8 | No new catalogue mutation or authority path | PASS | Read-only projection + matching; MCP tool surface unchanged (no write tool); no `data/**` mutation, no automerge/authority coupling; `test_legal_entity_enhancement_added_no_write_tool_or_authority` |
| 9 | Generated artifacts and schemas remain deterministic | PASS | `legal_entities` sorted by `entity_id`; build-twice byte-identical; `test_legal_entity_export_is_build_twice_deterministic`; no `build-indexes` drift |

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

The first independent review of this ratification PR (NOT_READY) found two genuine
correctness gaps in the bundled functionality and two guard-enforcement gaps. All were
addressed on a new head:

1. **Scope guard not enforced (finding 1).** Added `.github/workflows/pr-scope-guard.yml`
   — a required PR check that derives exactly one `Work-Package: WP-...` declaration from
   the PR body (fails closed on zero/multiple/unknown) and runs the guard against the
   exact base→head diff.
2. **Conflicting-identity false attribution (finding 2).** `select_with_legal_fallback`
   now fails closed when domain/name selects vendor A but the registration resolves to
   vendor B's entity — it attributes to neither and cross-links nothing
   (`registration_vendor_conflict`). Corrected once in the shared core, so the pack,
   snapshot and MCP surfaces all behave consistently.
3. **Public-source provenance (finding 3).** The exporter now projects only VERIFIED
   (canonical) legal entities — which carry verification source ids by schema invariant —
   and excludes unverified stubs; the audit fixture is a valid canonical record under the
   RAW legal-entity schema.
4. **Guard self-authorization (finding 4).** The CI guard evaluates the manifest AND the
   guard code from the **trusted base revision**, so a PR cannot weaken its own gate or
   expand its own allowlist in the same change; policy changes take effect only after they
   merge (and are human-reviewed).
5. **Stale doctrine (non-blocking).** Reconciled the `openva_mcp/matching.py` module
   docstring, which previously claimed the snapshot carries no legal-entity data.

## Verdict

The bundled legal-entity functionality is **ratified after correcting the two
review-found defects** (conflicting-identity fail-closed; verified-only export) and
**enforcing** the scope guard in CI from a trusted base. This PR carries the
audit evidence, the required corrections, the adversarial/parity/regression tests, the
enforced scope guard, and this record. It is opened for independent review and is not
merged autonomously.
