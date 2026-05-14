# Catalog Batch Generator

The catalog batch generator reduces repetitive vendor-catalog work by generating standard OpenVA vendor, source, and artifact records from a compact batch manifest.

Use it for small public-source catalog batches after source URLs have been reviewed.

## Scope

The generator creates only metadata records:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/{source_id}.yaml
data/vendors/{vendor_id}/artifacts/{artifact_id}.yaml
```

It does not fetch public pages, mirror raw documents, summarize source documents, access gated materials, or make legal, compliance, security, procurement, KYC, AML, or vendor-risk conclusions.

## Manifest location

Put batch manifests under:

```text
catalog-batches/
```

Example:

```text
catalog-batches/p26-apac-saas.yaml
```

## Manifest example

```yaml
schema_version: 0.1.0
batch_id: p26-apac-saas
collected_at: '2026-05-14T00:00:00Z'
observer: human
vendors:
  - vendor_id: asana
    display_name: Asana
    legal_name: Asana, Inc.
    headquarters_country: US
    regions_served:
      - global
    official_domains:
      - asana.com
    public_entrypoints:
      - https://asana.com/security
    vendor_categories:
      - enterprise_software
      - collaboration_software
      - project_management
    notes: Initial public-source catalog record for a major work management software provider.
    source:
      source_id: asana-security
      source_type: security_page
      title_native: Asana Security
      title_en: Asana Security
      source_url: https://asana.com/security
      source_language: en
      summary_native: Public Asana page describing security and trust information.
      summary_en: Public Asana page describing security and trust information.
    artifact:
      artifact_id: asana-security
      artifact_type: security_page
```

## Generate records

Run:

```bash
python -m tools.openva.catalog_batch catalog-batches/p26-apac-saas.yaml
```

To also rebuild indexes:

```bash
python -m tools.openva.catalog_batch catalog-batches/p26-apac-saas.yaml --build-indexes
```

Then run the normal validation set:

```bash
python -m tools.openva.validate validate
pytest -q
```

## Overwrite behavior

By default, the generator refuses to overwrite existing records. This prevents accidental replacement of reviewed catalog files.

To intentionally regenerate records for the same manifest:

```bash
python -m tools.openva.catalog_batch catalog-batches/p26-apac-saas.yaml --force
```

Use `--force` only when you intend to overwrite generated records.

## Defaults filled by the generator

The generator fills common OpenVA defaults:

```yaml
access_class: public_web
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

## Pull request guidance

Catalog batch PRs should still use the catalog guard title prefix:

```text
Catalog: PXX add {theme} catalog batch
```

For generator or schema changes, use the core lane instead of the catalog lane.
