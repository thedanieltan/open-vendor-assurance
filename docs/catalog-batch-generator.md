# Catalog Batch Generator

The catalog batch generator reduces repetitive vendor-catalog work by generating standard OpenVA vendor, source, artifact, and change-event records from a compact lifecycle manifest.

Use it for reviewed public-source catalog batches.

## Scope

The generator creates metadata records only:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/{source_id}.yaml
data/vendors/{vendor_id}/artifacts/{artifact_id}.yaml
data/vendors/{vendor_id}/changes/{change_id}.yaml
```

It does not fetch public pages, mirror raw documents, summarize source documents, access gated materials, or make legal, compliance, security, procurement, KYC, AML, or vendor-risk conclusions.

## Lifecycle operations

Every manifest declares one operation:

```yaml
operation: create
```

Supported operations:

```text
create
refresh
deprecate
```

`create` is for new vendor/source/artifact metadata.

`refresh` is for reviewed updates to existing public metadata such as DPA, subprocessors, privacy, security, or compliance references.

`deprecate` is for vendor/source/artifact lifecycle changes such as ceased operations, unavailable sources, moved sources, or no-longer-current metadata.

Each source entry emits a corresponding change event so the catalog behaves as a public metadata ledger.

## Manifest location

Put batch manifests under:

```text
catalog-batches/
```

Example:

```text
catalog-batches/cloudflare-one-vendor.yaml
```

## Manifest example

```yaml
schema_version: 0.1.0
batch_id: cloudflare-one-vendor
operation: create
collected_at: '2026-05-15T00:00:00Z'
observer: human
vendors:
  - vendor_id: cloudflare
    display_name: Cloudflare
    legal_name: Cloudflare, Inc.
    headquarters_country: US
    regions_served:
      - global
    official_domains:
      - cloudflare.com
    public_entrypoints:
      - https://www.cloudflare.com/trust-hub/
    vendor_categories:
      - cloud_infrastructure
      - security
      - developer_platform
    notes: Public-source-only catalog record for Cloudflare.
    sources:
      - source_id: cloudflare-dpa
        source_type: dpa
        title_native: Cloudflare Data Processing Addendum
        title_en: Cloudflare Data Processing Addendum
        source_url: https://www.cloudflare.com/cloudflare-customer-dpa/
        source_language: en
        access_class: public_web
        summary_native: Public Cloudflare data processing addendum metadata reference.
        summary_en: Public Cloudflare data processing addendum metadata reference.
        confidence: high
        artifact:
          artifact_id: cloudflare-dpa
          artifact_type: dpa
          region_scope:
            - global
          product_scope:
            - Cloudflare services
      - source_id: cloudflare-subprocessors
        source_type: subprocessors_list
        title_native: Cloudflare Subprocessors
        title_en: Cloudflare Subprocessors
        source_url: https://www.cloudflare.com/privacypolicy/subprocessors/
        source_language: en
        access_class: public_web
        summary_native: Public Cloudflare subprocessors metadata reference.
        summary_en: Public Cloudflare subprocessors metadata reference.
        confidence: high
        artifact:
          artifact_id: cloudflare-subprocessors
          artifact_type: subprocessors_list
          region_scope:
            - global
          product_scope:
            - Cloudflare services
```

## Generate records

Run:

```bash
python -m tools.openva.catalog_batch catalog-batches/cloudflare-one-vendor.yaml
```

To also rebuild indexes:

```bash
python -m tools.openva.catalog_batch catalog-batches/cloudflare-one-vendor.yaml --build-indexes
```

Then run the normal validation set:

```bash
python -m tools.openva.validate validate
pytest -q
```

## Overwrite behavior

For `create`, the generator refuses to overwrite existing records unless `--force` is used.

For `refresh` and `deprecate`, existing vendor/source/artifact records are intentionally updated, while change-event records are still protected from accidental overwrite unless `--force` is used.

## Defaults filled by the generator

The generator fills common OpenVA defaults:

```yaml
rights_class: metadata_only
not_advice: true
hashes:
  raw_sha256: sha256:TBD
  normalized_text_sha256: sha256:TBD
storage:
  raw_document_stored: false
  extracted_text_stored: false
  screenshot_stored: false
source_policy:
  public_sources_only: true
  gated_materials_excluded: true
  raw_documents_mirrored_by_default: false
```

Source `access_class` defaults to `public_web` when not supplied.

## Pull request guidance

Catalog batch PRs should use the catalog guard title prefix:

```text
Catalog: ...
```

For generator or schema changes, use the core lane instead:

```text
P: ...
```
