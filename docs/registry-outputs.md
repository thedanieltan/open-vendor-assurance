# Registry Outputs

OpenVA generates user-facing registry outputs from the same public-source metadata used to build the core indexes.

## Vendor manifests

Vendor manifests are generated at:

```text
dist/vendors/{vendor_id}.json
```

Each manifest contains:

```text
vendor
canonical_sources
artifacts
observations
changes
legal_entities
entity_mentions
candidate_sources
unavailable_sources
summary
guarantees
```

Candidate sources remain non-canonical. Unavailable sources remain reviewed absence or omission records.

## Search index

The vendor search index is generated at:

```text
indexes/vendor-search.json
```

It provides a compact consumer-facing view of vendors, domains, canonical source types, candidate source types, unavailable source types, and manifest paths.

## Source coverage index

The source coverage index is generated at:

```text
indexes/source-coverage.json
```

It summarizes canonical, candidate, and unavailable source-type counts.

## Contracting entity resolution index

The contracting entity resolution index is generated at:

```text
indexes/contracting-entity-resolution.json
```

It contains generated resolution entries for canonical legal entities only. Stub legal entities and unresolved observed mentions are excluded.

Resolution statuses describe available public evidence:

```text
resolved
candidate
ambiguous
brand_only_fallback
```

These statuses do not determine current corporate status, legal effect, approval, suitability, risk, compliance, or contracting authority for any customer.

## Pack manifest

`openva-pack.json` advertises these outputs through:

```text
indexes.vendor_search
indexes.source_coverage
indexes.contracting_entity_resolution
registry_outputs.vendor_manifests
```

See `docs/adapter-contract.md` for supported import semantics.

## Guardrails

Registry outputs are metadata-first and non-advisory. They do not approve, recommend, certify, score, or determine whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.

Raw vendor documents are not mirrored by default.
