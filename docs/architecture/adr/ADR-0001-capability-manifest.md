# ADR-0001: Single generated capability manifest

Status: **Proposed** (implemented + locally verified on `refactor/openva-four-planes`; not deployed; not live-accepted).
Work package: WP-OPENVA-FOUR-PLANE-FOUNDATION-01.

## Context
Source-type definitions and cross-runtime contract versions were maintained independently in
at least five places: `config/controlled-vocabulary.yaml` (15), the `candidate-source` schema
enum (15), the browser `CONTROLLED_SOURCE_TYPES`/`DEFAULT_SELECTED_TYPES` arrays, the Python
`SOURCE_TYPE_REGISTRY` (9), and `RESULT_PACK_VERSION`. They had already drifted (registry = 9
vs vocabulary = 15).

## Decision
`config/openva-capabilities.yaml` becomes the single source of truth for source types, aliases,
per-transport availability, and contract versions (`schema_version`, `resolver_contract_version`,
`result_pack_version`). `tools/openva/capabilities.py` generates downstream artifacts
(`site/src/generated/openva-capabilities.generated.js`) and provides a `check` mode that **fails
closed** when any locked surface or the generated artifact drifts. The check is wired into
`tools.openva.validate.validate_all`.

## Consequences
- Additive and backward-compatible: existing surfaces are unchanged; the manifest is asserted to
  *agree* with them, so drift is caught without rewiring every consumer yet.
- Follow-on (later increment): rewire browser/Worker/Python consumers to import the generated
  artifact and remove the hand-maintained copies once the lock has proven stable.
- `discovery_supported` is modelled as the subset the discovery pipeline actually supports (9),
  not forced to the full 15 — preserving current discovery behaviour.
- `live_resolver_supported` is a declared target contract, conformance-verified later in
  WP-OPENVA-LIVE-RESOLVER-BOUNDARY (the Worker does not enumerate source types today).

## Alternatives considered
- Extend `controlled-vocabulary.yaml` in place: rejected — it mixes many unrelated vocabularies;
  a dedicated capability manifest is clearer and versioned independently.
- Rewire all consumers immediately: rejected for this increment — higher blast radius; the
  consistency lock delivers the core value (no independent drift) at far lower risk.
