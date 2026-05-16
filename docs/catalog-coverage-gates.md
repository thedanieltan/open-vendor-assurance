# Catalog Coverage Gates

OpenVA uses catalog coverage gates to keep vendor metadata expansion useful without turning coverage into a risk score, compliance determination, vendor approval, procurement recommendation, or legal conclusion.

These gates describe catalog completeness only.

## Core artifact depth

For public vendor assurance records, the preferred baseline is five public metadata references when available:

```text
dpa
subprocessors_list
privacy_notice
security_page or trust_center
compliance_page or certification_reference
```

A vendor record may still be accepted with fewer references when public sources are sparse, blocked, consolidated into one public legal page, or require later refinement. In that case the source confidence and record notes should make the limitation visible.

## Breadth gate

Catalog breadth measures the number of materialized vendor records with canonical records under:

```text
data/vendors/{vendor_id}/vendor.yaml
```

Near-term breadth target:

```text
150 materialized vendors
```

Maturity breadth target:

```text
250 materialized vendors
```

These are public-catalog coverage targets only. They do not imply that any vendor is suitable, safe, compliant, approved, or recommended.

## Depth gate

Catalog depth measures whether materialized vendors have multiple public assurance metadata references instead of shallow one-artifact records.

Minimum useful public baseline:

```text
top 25 tier-1 vendors have at least 4 core artifact types
no tier-1 vendor remains a one-artifact record when public sources are available
DPA coverage materially improves across tier-1 vendors
subprocessor-list coverage materially improves across tier-1 vendors
```

Near-term maturity target:

```text
top 50 vendors have at least 3 core artifact types
high-sensitivity categories are prioritized for depth
one-artifact records are treated as backlog unless no better public source exists
```

High-sensitivity categories include, but are not limited to:

```text
cloud_infrastructure
identity
access_management
security
hris
finance_platform
data_platform
ai_platform
```

## Batch PR declaration

Catalog batch PRs should state whether they primarily add:

```text
breadth
artifact depth
both breadth and depth
```

Generated catalog PRs should include the batch manifest and generated indexes in the same PR.

## Source-confidence handling

Coverage depth does not require pretending every public source has equal quality. When a source is an entrypoint, consolidated legal page, public PDF, public trust page, or needs later refinement, set an appropriate confidence value:

```text
low
medium
high
```

Use notes where needed. Do not turn confidence into a vendor rating.

## Entity-surface handling

Where a vendor exposes distinct international, mainland/native, regional, product, or brand public assurance surfaces, coverage should be measured against the specific OpenVA vendor record rather than collapsing related records.

Related records may use:

```yaml
entity_family: example-family
entity_surface: international
related_vendor_ids:
  - example-native-record
source_authority_language: en
```

## Release-readiness posture

A public launch or release note should not claim catalog maturity based on vendor count alone. It should consider both:

```text
vendor breadth
artifact depth
```

The catalog can still be useful before reaching maturity, provided the limitation is visible and non-advisory.

## Non-advisory boundary

Coverage gates are not:

```text
risk scores
legal opinions
compliance determinations
security ratings
procurement recommendations
vendor approvals
market availability conclusions
```

They are only internal/public catalog-completeness gates for OpenVA metadata maintenance.
