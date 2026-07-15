# Source Publisher Attribution and Product Applicability

OpenVA distinguishes the product represented by a vendor record from the organization or service that publishes a source URL.

A source hosted outside the product's primary domain may be canonical only when OpenVA records both:

1. `publisher_attribution`: who publishes the source and the publisher's relationship to the product; and
2. `applicability`: why the source covers the product represented by `vendor_id`.

This metadata is factual source provenance. It is not legal, compliance, procurement, security, audit, suitability, approval, or vendor-risk advice.

## Publishing relationships

- `self`: the selected product publishes the source directly;
- `parent`: a verified parent company publishes a centralized source;
- `affiliate`: another entity in the same corporate group publishes the source;
- `regional_entity`: a regional operating or contracting entity publishes the source;
- `authorized_host`: an authorized status, trust, or document host publishes the source;
- `public_authority`: a public authority publishes the source.

## Admission behavior

The catalog guard applies a changed-record gate:

- same-product-domain sources remain compatible with existing records;
- newly added or modified cross-domain sources require complete publisher attribution and verified applicability;
- existing cross-domain records are inventoried by the report-only source attribution audit and can be backfilled in bounded catalog work packages;
- incomplete or ambiguous attribution fails closed for changed records.

Run the report-only audit with:

```bash
python -m tools.openva.source_attribution audit --output source-attribution-audit.json
```

`coverage-audit.yml` runs this audit on its existing weekly schedule and includes `source-attribution-audit.json` in the coverage artifact bundle. This keeps attribution completeness within the existing catalog-quality loop rather than adding another scheduled workflow.

## Public presentation

The vendor detail surface displays, before a cross-domain link:

- the source publisher;
- the relationship to the selected product;
- the destination domain;
- the covered product;
- the recorded coverage basis; and
- a disclosure containing the applicability statement and evidence link.

CSV, SQLite, site JSON, and selected-source JSON exports preserve the same structured metadata.
