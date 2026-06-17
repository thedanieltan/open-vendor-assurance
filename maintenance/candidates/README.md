# Candidate records store

Unified `candidate_record` JSON files, one per candidate, keyed by deterministic
`candidate_id` (`<candidate_id>.json`). The convergence point for every candidate
origin; on its schedule the autonomous catalog-growth controller globs this
directory and selects records by their committed `eligibility_state` (recomputation
of that state against the resolver's own evaluation is a documented follow-up — see
`docs/candidate-intake.md`).

This is operational candidate **staging**, not canonical catalog data — never
`data/**`. Records are written by the unified resolver's durable ingress
(`tools/openva/vendor_resolution.py` — `CatalogQueueIngress`, the single canonical
writer: atomic, file-locked, idempotent merge) and reach `main` only through the
candidate-intake PR path, never a direct write. Every record validates against
`schemas/openva/candidate-record.schema.json`.

Operational metadata only. Not legal, compliance, procurement, security, KYC,
AML, audit, or vendor-risk advice.
