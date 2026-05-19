# Category Coverage Program

OpenVA uses categories as controlled metadata tags, not as standalone vendor entities.

The canonical vendor model remains:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/*.yaml
data/vendors/{vendor_id}/artifacts/*.yaml
```

Category coverage is derived from metadata fields such as:

```yaml
vendor_categories:
  - cloud_infrastructure
  - enterprise_software
  - developer_platform

regions_served:
  - global
  - APAC
  - CN

artifact_type: dpa
```

The controlled vocabulary lives in:

```text
config/category-taxonomy.yaml
```

## Why categories are metadata tags

Many vendors operate across multiple markets and product surfaces. A rigid category object or category folder would create false exclusivity.

Examples:

```text
Microsoft: cloud infrastructure, productivity software, identity, developer platform, AI platform
Salesforce: CRM, marketing technology, customer engagement, analytics, enterprise software
Stripe: payments, financial infrastructure, billing, identity/risk adjuncts
Alibaba Cloud: cloud infrastructure, regional APAC, mainland China, AI/data adjacent services
```

Because of this, OpenVA should tag vendors and artifacts with controlled metadata, then compute coverage by tag.

## Coverage lanes

Coverage lanes are planning and reporting groupings. They are not canonical data entities.

The current lanes are defined in `config/category-taxonomy.yaml` under:

```yaml
coverage_lanes:
```

Each lane declares:

```yaml
vendor_category_tags:
  - controlled_tag

target_materialized_vendors: 50
target_deep_vendors: 25
tier_1_min_core_artifacts: 3
```

## Breadth and depth rule

A lane is not healthy just because it has many vendors. It needs both breadth and artifact depth.

Breadth means materialized vendors under `data/vendors/`.

Depth means useful public assurance artifacts per vendor.

Core artifact types:

```text
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_page
```

## Public usefulness baseline

OpenVA should not be treated as mature until it reaches at least:

```text
150 materialized vendors
top 25 tier-1 vendors with at least 4 core artifact types
no tier-1 vendor with only one artifact
materially improved DPA coverage
materially improved subprocessor-list coverage
```

Near-term target:

```text
250 materialized vendors
top 50 vendors with at least 3 core artifact types
stronger APAC, mainland China, EU, and sector-specific coverage
```

## PR classification

Every catalog PR should state whether it is primarily:

```text
breadth expansion
depth enrichment
breadth + depth
materialization of pending batch manifests
source-quality tooling
```

Broad expansion should pause if coverage audits show that depth is not improving.

## Non-advisory boundary

Coverage lanes, category tags, and depth indicators are catalog-completeness metadata only.

They do not mean:

```text
vendor is compliant
vendor is safe
vendor is recommended
vendor is approved
vendor is low risk
vendor satisfies any legal, regulatory, audit, procurement, or security requirement
```

## Stop conditions

Pause broad category expansion if:

- exact or semantic duplicates are appearing;
- generated indexes drift;
- many vendors have only `other_public_artifact` records;
- DPA and subprocessor-list coverage remains stagnant;
- non-English sources are being flattened into English-only summaries;
- contributors start adding gated, customer-only, NDA, or portal materials.

## Execution sequence

Recommended sequence:

1. materialize already-merged executable batch manifests;
2. deepen tier-1 cloud, productivity, CRM, payments, HR, security, AI/data, and APAC vendors;
3. add new breadth only when each lane has a depth target and source-quality review plan;
4. run coverage audit after each batch group;
5. update public-readiness status from coverage audit deltas.
