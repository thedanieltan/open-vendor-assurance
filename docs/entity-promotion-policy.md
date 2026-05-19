# Entity Promotion Policy

OpenVA separates observed entity mentions from canonical legal entity records.

## Observed Mentions

Observed mentions may be recorded from vendor-published public sources without independent verification. They capture what the public source names, when OpenVA observed it, and where it appeared.

Observed mentions do not verify corporate existence, status, registration, authority, or contracting role.

## Canonical Entities

A canonical legal entity record requires at least one verification source with one of these `source_authority_class` values:

```text
public_registry
public_authority
court_or_regulatory_filing
vendor_legal_terms
```

`public_registry` is preferred where available. Other classes may be used when public registry evidence is unavailable or not applicable, with confidence reflected in the record and generated indexes.

## Promotion

Promotion from an observed mention to a canonical legal entity is an editorial act and requires human review. Agent-generated promotions must enter through pull requests and must not merge without maintainer approval.

When a mention is matched to a canonical entity, the mention must record match method, confidence, reviewer or agent, source IDs, and match timestamp.

Cross-vendor entity references are valid. An entity mention under one vendor may resolve to a canonical entity stored under another vendor's package. Validators resolve `entity_id` globally.

Only `catalog_status: canonical` entities enter the contracting-entity resolution index. Stub records and unresolved mentions remain queryable as catalog metadata but are excluded from resolution outputs.
