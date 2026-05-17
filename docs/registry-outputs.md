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

## Pack manifest

`openva-pack.json` advertises these outputs through:

```text
indexes.vendor_search
indexes.source_coverage
registry_outputs.vendor_manifests
```

## Guardrails

Registry outputs are metadata-first and non-advisory. They do not approve, recommend, certify, score, or determine whether any vendor is compliant, safe, adequate, suitable, low risk, or high risk.

Raw vendor documents are not mirrored by default.
