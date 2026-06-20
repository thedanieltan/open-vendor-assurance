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
| 1 | Registration fallback creates no false-positive matches | PASS | Empty / whitespace / unknown registration → no match (`select_with_legal_fallback` only selects on a unique resolved entity); `test_no_false_positive_on_empty_or_unknown_registration` |
| 2 | Ambiguous registration fails closed | PASS | Two vendors sharing a registration → `no_match` (resolution `ambiguous`, no vendor selected); `test_ambiguous_registration_fails_closed_and_jurisdiction_disambiguates` |
| 3 | Jurisdiction handling is deterministic | PASS | Snapshot rows carry no jurisdiction → ambiguous-without-jurisdiction conservatively fails closed; a supplied jurisdiction deterministically disambiguates; same test |
| 4 | Pack / snapshot / MCP / agent-export behaviourally consistent | PASS | Both surfaces call the SAME `core.select_with_legal_fallback` (not a fork); `test_snapshot_and_pack_share_one_registration_authority`, `test_matching_conformance`, `test_openva_enrichment_parity` |
| 5 | Vendors without legal entities stay backward-compatible | PASS | The optional `legal_entities` key is emitted only when present, so the shipped catalogue (no legal entities) is byte-identical; `test_vendor_without_legal_entities_is_backward_compatible` |
| 6 | Optional export fields comply with the versioning policy | PASS | Additive optional field within `0.1.x` (versioning-policy §"Backward-compatible optional field additions"); consumers safely ignore it; `schema_version` unchanged |
| 7 | Legal-entity metadata is public-source-backed and non-advisory | PASS | Projection carries only public identity fields (incl. `registered_address`); a legal-entity-bearing export passes the leakage, advisory, non-advisory-doctrine and digest gates; `test_legal_entity_export_passes_all_release_gate_scanners` |
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

## Verdict

The bundled legal-entity functionality is **sound and ratified**. No revert and no
functional correction were required. This PR adds the adversarial/parity/regression
evidence, the scope guard that prevents recurrence, and this record. It is opened for
independent review and is not merged autonomously.
