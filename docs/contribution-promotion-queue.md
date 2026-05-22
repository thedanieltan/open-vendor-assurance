# Contribution Promotion Queue

The contribution promotion queue collates contributor-submitted vendor/source updates before any source reference is promoted to canonical catalog metadata.

It is intentionally a reporting and planning layer. It does not write canonical source files, open pull requests, or auto-merge changes.

## Inputs

The queue can read:

```text
.openva-intake/intake-report.json
catalog-batches/intake/*.yaml
```

These inputs may come from issue intake, agent-discovered catalog batches, or manually prepared contributor update batches.

## Processing model

The queue:

1. loads contributor intake reports and catalog batch manifests;
2. normalizes candidate source references;
3. deduplicates candidates by `vendor_id + source_type + normalized URL`;
4. preserves submission provenance for repeated contributor submissions;
5. applies the machine-canonical eligibility gates from `tools.openva.auto_canonical`;
6. emits observation records for verification results;
7. splits output into machine-validated promotions, human-review-required items, and rejected items.

## Output buckets

### `machine_validated_promotions`

Source references that passed machine-canonical gates.

These are canonical public source references only. They do not assert compliance, approval, risk level, legal adequacy, procurement suitability, KYC/AML adequacy, sanctions status, or certification validity.

### `human_review_required`

Items that may be useful but failed one or more machine-canonical gates in a way that requires human judgment.

Typical examples:

- missing verification;
- source type mismatch;
- unknown vendor identity;
- unsafe or cross-domain redirects;
- legal/entity ambiguity;
- source authority ambiguity.

### `rejected`

Items that violate OpenVA boundaries, such as advisory wording or raw/extracted document text.

### `observations`

Non-canonical fetch observations derived from verification results.

Required posture:

```text
canonical: false
catalog_tier: observation
review_state: auto_observed
advisory_boundary: non_advisory
```

## CLI

```bash
python -m tools.openva.contribution_promotion_queue build \
  --intake .openva-intake \
  --batch catalog-batches/intake \
  --out .openva-promotion-queue/queue.json
```

For tests or alternate roots:

```bash
python -m tools.openva.contribution_promotion_queue build \
  --root /path/to/openva-checkout \
  --intake /path/to/intake-reports \
  --out /tmp/queue.json
```

## Non-advisory boundary

The queue only classifies source-reference promotion readiness. It does not approve vendors, certify vendors, recommend vendors, score vendor risk, or produce legal/compliance/procurement/security/KYC/AML/sanctions conclusions.
