# Controlled Catalog Reset — 2026-05-15

OpenVA is resetting its catalog-growth model before public launch.

This is a controlled reset of the catalog layer and contribution policy, not a reset of the repository substrate.

## Why this reset is needed

The early catalog expansion optimized for safe contribution mechanics and breadth exploration:

```text
schemas
metadata-only posture
public-source-only policy
catalog batch manifests
validation
agent PR guardrails
source-health reports
coverage audit
category taxonomy
```

Those pieces are useful and should be preserved.

However, the catalog itself became too shallow. The first coverage audit showed:

```text
vendor_count: 62
artifact_count: 62
vendors_with_dpa: 11
vendors_with_subprocessors_list: 3
vendors_with_at_least_three_core_artifacts: 0
```

This means OpenVA had many one-artifact vendor records and too little DPA/subprocessor/compliance depth for a useful public-good release.

The repo also developed a misleading distinction between planned breadth and materialized breadth:

```text
catalog-batches/*.yaml = proposed or planned vendors
data/vendors/** = canonical materialized vendors
indexes/*.json = generated public catalog outputs
```

Batch manifests were useful as review inputs, but they should not have been treated as catalog progress unless canonical records were generated immediately.

## Reset decision

OpenVA will move from:

```text
batch manifest first, materialization later
```

to:

```text
canonical records in the same PR, generated indexes in the same PR, validation in the same PR
```

A catalog PR is not complete unless it includes:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/*.yaml
data/vendors/{vendor_id}/artifacts/*.yaml
indexes/*.json
openva-pack.json
```

when those outputs are affected.

## What is preserved

The following repository substrate remains valuable and should be preserved:

```text
schemas/
policy/
config/category-taxonomy.yaml
tools/
tests/
docs/
.github/workflows/
README.md
CONTRIBUTING.md
SECURITY.md
LICENSE
```

## What may be reset or rebuilt

The following catalog layer may be deleted, archived, or regenerated as part of reseed work:

```text
data/vendors/
indexes/
openva-pack.json
catalog-batches/ stale or unmaterialized manifests
```

Resetting these files is acceptable when the replacement PR reseeds higher-quality canonical records.

## New catalog-entry rule

A vendor should enter the canonical catalog only when one of these is true:

1. it has useful public assurance artifacts; or
2. it is a tier-1/material vendor and the missing public artifacts are explicitly recorded as catalog coverage gaps.

Useful public assurance artifacts include:

```text
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_page
ai_terms
data_transfer_terms
product_terms
shared_responsibility_model
```

## Minimum reseed standard

For tier-1 vendors, reseed PRs should aim for at least four core artifact types:

```text
dpa
subprocessors_list
privacy_notice
security_page or trust_center
compliance_page
```

Where a public artifact is unavailable, the PR should not invent a substitute. It should record a coverage gap or omit the artifact until a public source is available.

## Public-source-only boundary

The reset does not weaken source rules.

Do not include:

- customer-specific agreements;
- negotiated DPAs;
- private order forms;
- NDA materials;
- authenticated trust-center documents;
- private SOC reports;
- private ISO certificates;
- portal-only downloads;
- summaries of non-public materials.

## Native-language boundary

For non-English public sources, the native-language source remains authoritative. English summaries are convenience metadata only.

## Non-advisory boundary

Catalog depth, category coverage, and artifact completeness are not vendor ratings.

They do not mean:

```text
vendor is compliant
vendor is safe
vendor is recommended
vendor is approved
vendor is low risk
vendor satisfies any legal, regulatory, audit, procurement, or security requirement
```

## Reseed sequence

Recommended reseed sequence:

1. tier-1 cloud and platform vendors;
2. tier-1 payments, fintech, KYC, and risk vendors;
3. tier-1 HR, workforce, education, and healthcare vendors;
4. tier-1 AI, data, developer, security, and observability vendors;
5. tier-1 collaboration, CRM, customer engagement, support, and marketing vendors;
6. APAC/mainland China/regional vendors with native-language source retention;
7. broader category breadth after depth stabilizes.

## Success criteria

Minimum public-usefulness baseline:

```text
150 materialized vendors
top 25 tier-1 vendors with at least 4 core artifact types
no tier-1 vendor with only one artifact
materially improved DPA coverage
materially improved subprocessor-list coverage
```

Near-term maturity target:

```text
250 materialized vendors
top 50 vendors with at least 3 core artifact types
all major category lanes represented
APAC/mainland China coverage retained with native-language sources where available
```
