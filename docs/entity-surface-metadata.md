# Entity Surface Metadata

OpenVA uses entity-surface metadata to distinguish related public vendor records without merging distinct legal, regional, language, or product contexts.

This matters for vendors whose international-facing, mainland/native, regional, or product-specific public assurance materials differ.

## Fields

The intended vendor-level fields are:

```yaml
entity_family: alibaba-cloud
entity_surface: international
related_vendor_ids:
  - aliyun
source_authority_language: en
```

For a native mainland record:

```yaml
entity_family: alibaba-cloud
entity_surface: mainland_china
related_vendor_ids:
  - alibaba-cloud-international
source_authority_language: zh
```

## Semantics

`entity_family` is a grouping key. It is not a legal identity claim.

`entity_surface` describes the public metadata surface represented by the record. It does not determine contracting coverage, regulatory scope, data residency, market availability, compliance, adequacy, risk, or vendor suitability.

`related_vendor_ids` links related OpenVA vendor records without merging them.

`source_authority_language` records which language should be treated as authoritative for the public source set attached to that vendor record.

## Controlled values

Allowed entity-surface values are defined in:

```text
config/entity-surface-taxonomy.yaml
```

Initial values:

```text
international
mainland_china
hong_kong
singapore
global_brand
product_surface
regional_surface
unknown
```

## Contributor rule

Do not collapse related vendor records when their public sources, domains, languages, legal names, or regional surfaces differ. Create separate records and connect them with `entity_family` and `related_vendor_ids`.

## Non-advisory boundary

Entity-surface metadata is public catalog metadata only. It must not be used to imply that a vendor is approved, safe, compliant, adequate, low risk, high risk, available, or suitable for any procurement or legal purpose.
