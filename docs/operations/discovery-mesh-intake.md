# Discovery mesh intake

The discovery mesh stages verified candidate-source records and one reviewed promotion plan per vendor. The intake is deliberately noncanonical.

Allowed intake paths:

- `data/vendors/<vendor_id>/candidate_sources/<candidate_id>.yaml`
- `maintenance/reviewed/discovery-mesh/<run_token>/<vendor_id>.json`

The intake guard requires public HTTP 200 evidence, semantic matched terms, an official-domain candidate URL, an official-domain final URL, `requires_review: true`, and `not_advice: true`.

Every staged candidate must be referenced by exactly one same-intake reviewed plan. Every plan contains actions for exactly one vendor. There is no catalog vendor-count ceiling and no total action-count ceiling; the per-vendor plans are execution isolation units, not catalog caps.

No intake PR may write canonical vendor, source, artifact, change, index, distribution, or machine-decision records. `candidate-promotion-pr.yml` remains the sole canonical mutation authority.
