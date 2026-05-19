# Adapter Output Contract

OpenVA adapters may add a small normalization layer around source pack records. These fields are adapter annotations, not source-catalog fields.

## Required annotations

Every normalized adapter record must include:

```text
record_class
canonical
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
