# Adapter Output Contract

OpenVA adapters may add a small normalization layer around source pack records. These fields are adapter annotations, not source-catalog fields.

## Required annotations

Every normalized adapter record must include:

```text
record_class
canonical
catalog_tier
review_state
advisory_boundary
```

`record_class` preserves the source record group:

```text
canonical
candidate
unavailable
observation
artifact
vendor
change
coverage
```

`canonical` is true only for accepted OpenVA canonical source references. Candidate sources, unavailable-source ledger entries, observations, artifacts, vendors, changes, and coverage rows must not be treated as canonical source records.

## Tier and review-state annotations

Every normalized adapter record must preserve:

- `record_class`
- `canonical`
- `catalog_tier`
- `review_state`
- `advisory_boundary`

`catalog_tier` describes how far a metadata record has moved through the
OpenVA publication pipeline. It is not a vendor rating, approval status,
assurance score, compliance finding, procurement recommendation, contracting
verification, KYC/AML status, sanctions status, or risk conclusion.

It is not a compliance finding and not a risk conclusion.

Current tier values are:

```text
discovery
observation
machine_validated
human_reviewed
```

`review_state` describes OpenVA's review state for the metadata record only.
It does not describe the vendor's legal, security, compliance, procurement,
KYC, AML, sanctions, operational, or contractual status.

Consumers must preserve these fields when importing OpenVA outputs so
candidate records, machine-observed facts, machine-validated records, and
human-reviewed canonical records are not collapsed into a single source
availability or assurance claim.

`advisory_boundary` must be:

```text
non_advisory
```

This constant is for multi-source downstream systems that need a machine-readable boundary distinguishing OpenVA public metadata from sources that make risk, compliance, approval, or suitability assertions.

## Transition aliases

Adapters must prefer:

```text
catalog_status
catalog_change_significance
```

During the `v0.1.x` line, adapters may read deprecated aliases:

```text
status
materiality
```

The deprecated aliases are removed from generated outputs in `v0.2.0` or `openva-export-pack.v2`, whichever ships first.

## Boundary

Adapter annotations must not collapse canonical, candidate, unavailable, or observation records into a single source-availability claim.
