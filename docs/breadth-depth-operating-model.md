# Breadth and Depth Operating Model

OpenVA is useful only when it has both breadth and depth.

Breadth means the catalog covers enough material vendors across software categories, regions, and public assurance surfaces to be useful as a public substrate.

Depth means each material vendor has more than a single generic trust or security page. The repository should prefer factual references to public assurance artifacts such as DPAs, subprocessor lists, privacy notices, trust centers, security pages, compliance/certification pages, product terms, AI terms, and data-transfer terms.

This document defines how OpenVA should grow without drifting into advice, vendor scoring, or private-material collection.

## Current operating principle

```text
materialized vendor records + public artifact references + validation + human review
```

A vendor is not considered covered merely because it appears in a backlog, batch manifest, or PR description. A vendor is counted as materialized only when it has committed records under:

```text
data/vendors/{vendor_id}/vendor.yaml
data/vendors/{vendor_id}/sources/*.yaml
data/vendors/{vendor_id}/artifacts/*.yaml
```

and the generated indexes have been rebuilt.

## Public usefulness targets

Near-term targets:

```text
minimum materialized vendors: 150
near-term materialized vendors: 250
```

Depth targets:

```text
tier-1 vendors: at least 4 core artifact types
general vendors: at least 2 core artifact types
```

Core artifact types:

```text
dpa
subprocessors_list
privacy_notice
security_page
trust_center
compliance_page
```

Additional useful artifact types include:

```text
ai_terms
data_transfer_terms
product_terms
security_whitepaper
shared_responsibility_model
incident_response_page
```

## Coverage score boundary

OpenVA may compute catalog completeness indicators, but these are not legal, compliance, procurement, security, or vendor-risk scores.

A coverage or depth score means only:

```text
how complete the public metadata record is compared with OpenVA's catalog targets
```

It does not mean:

```text
vendor is compliant
vendor is safe
vendor is recommended
vendor is low risk
vendor satisfies a regulation
vendor is suitable for a workload
```

## Expansion order

OpenVA should expand in this order:

1. materialize already-merged catalog batch manifests that have not produced vendor records;
2. deepen tier-1 vendors with DPA, subprocessor, privacy, security/trust, and compliance pages;
3. deepen sensitive-data categories such as KYC, payments, HR, healthcare, education, identity, data enrichment, and AI;
4. continue breadth expansion by category once depth coverage is improving;
5. revisit live observation and hash workflows only after source metadata coverage is materially stronger.

## Tier-1 vendor depth target

Tier-1 vendors include major cloud, productivity, CRM, payments, HR, identity, AI, data, and security platforms. For these vendors, OpenVA should aim to reference at least:

```text
DPA
subprocessor list
privacy notice
trust center or security page
compliance/certification page
```

Where public sources are unavailable, the correct action is to record the gap in an audit report or backlog. Do not use gated portals, NDA materials, customer-only reports, or private trust-center documents.

## Public-source-only rule remains controlling

Depth must not be achieved by weakening source rules.

Do not add:

- customer-specific agreements;
- negotiated DPAs;
- private order forms;
- NDA materials;
- authenticated trust-center documents;
- private SOC reports;
- private ISO certificates;
- portal-only downloads;
- summaries of non-public materials.

## Native language policy remains controlling

For non-English sources, retain native-language authority. English summaries are convenience metadata only.

## Review policy

Coverage audit outputs should be used to plan catalog work. They should not be presented as vendor ratings.

Every breadth/depth PR should state whether it:

```text
materializes pending batch manifests
deepens existing vendors
adds new vendors
adds source-quality tooling
```

PRs should avoid mixing all four unless the change is small and reviewable.
