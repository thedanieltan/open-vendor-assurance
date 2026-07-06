# Portfolio Provenance & Source-Fidelity Vocabulary — v0.1.0 (PROVISIONAL)

A neutral, versioned contract for tagging any record, artifact, or datum with the fidelity of its source. Each project maps its own existing notion onto these tiers and vendors a pinned copy. No project owns it; changes are versioned.

## Tiers (`tier`)
- `synthetic` — produced by a deterministic simulation/model; no real-world source.
- `sandbox` — obtained from / projected into a real external system in test/sandbox mode (real API shapes, no production data).
- `connected` — obtained from a real production external system (real tenant/customer data).
- `public-source` — factual metadata compiled from publicly published sources.
- `authored` — human-authored interpretation or content.
- `derived` — computed from other provenance-tagged inputs.

## Fields
- `tier` (required), `source_ref` (opt), `captured_at` (opt; for `synthetic` use simulation time, never wall-clock), `fidelity_note` (opt), `contract_version` (required = "0.1.0").

## Rules
- Derived min-fidelity (no laundering): a `derived` record's effective trust is the lowest tier among its inputs. Transforming `synthetic` never makes it `connected`.
- Honesty: absence of a real source is tagged `synthetic`, never implied real.
- Neutral & vendored: each repo pins its own copy.

## Reference mappings
- Aether: engine artifacts → `synthetic`; sandbox-connector artifacts → `sandbox`; (future) Connected Mirror → `connected`.
- Compliance OS: existing evidence-provenance/quarantine model; imported standards → `public-source`/`authored`; fixtures → `synthetic`.
- OpenVA: catalog records → `public-source` (verification-status refines) — reference implementation.
- TaxCraft: `SourceRef.fictional` → `synthetic`; real jurisdiction sources → `public-source`/`authored`.
- FMR: deterministic outputs → `synthetic`; SEC/live-adapter → `public-source`/`connected`.
