# Architecture

OpenVA is a public vendor assurance data substrate.

It should maintain its own canonical public-data model and export consumer-neutral packs.

## Layering

```text
OpenVA native substrate
  -> OpenVA universal export pack
  -> consumer compatibility profiles
  -> downstream runtime imports
```

## OpenVA owns

- vendor public profiles;
- public source references;
- public artifact references;
- source access classification;
- rights classification;
- native-language metadata;
- source observations;
- freshness metadata;
- factual change events;
- public questionnaire and evidence request templates.

## Downstream runtimes own

- workspace vendor records;
- user-specific vendor reviews;
- risk decisions;
- approval workflows;
- private evidence uploads;
- audit events;
- control mappings;
- jurisdiction-specific or tenant-specific obligation impact;
- final legal, compliance, procurement, security, KYC, AML, or vendor-risk decisions.

## Universal export principle

The primary export should be OpenVA-owned and consumer-neutral.

Specific consumers, including Compliance OS, may use compatibility profiles. OpenVA should not become a single-application module repository.
