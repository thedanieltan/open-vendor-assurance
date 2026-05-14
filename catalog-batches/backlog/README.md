# Catalog Batch Backlog

This directory is reserved for candidate catalog-batch planning notes.

Backlog files are not generated catalog records. They are planning artifacts for future agent or maintainer work.

## Purpose

Use backlog files to track:

- candidate vendor themes;
- regional gaps;
- source-discovery status;
- vendors requiring human review;
- candidates rejected because sources were gated, unclear, or not vendor-controlled.

## Rules

Backlog entries must remain metadata-only and non-advisory.

Do not include:

- raw documents;
- copied contract text;
- screenshots;
- gated or portal materials;
- vendor scores;
- legal or compliance conclusions;
- procurement recommendations.

## Suggested entry shape

```yaml
theme: identity-security
status: candidate
notes: Candidate vendors for a future catalog batch.
vendors:
  - display_name: Example Vendor
    candidate_vendor_id: example-vendor
    candidate_region: global
    source_discovery_status: needs_review
    candidate_public_sources:
      - https://example.com/security
    review_notes: Public security page appears vendor-controlled; DPA page not yet identified.
```

## Promotion to catalog batch

A backlog candidate becomes a catalog batch only when a maintainer assigns a phase label and an agent creates:

```text
catalog-batches/pXX-theme.yaml
```

The generator should then create records under:

```text
data/vendors/**
```
