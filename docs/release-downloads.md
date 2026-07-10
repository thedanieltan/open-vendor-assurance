# OpenVA release downloads

OpenVA publishes spreadsheet-friendly and machine-readable catalog snapshots through GitHub Releases.

Use these files when you want public vendor assurance source metadata without installing Python, running Docker, or operating a service.

**Browser resolver:** https://thedanieltan.github.io/open-vendor-assurance/

## Main downloads

### `openva-csv.zip`

The main non-technical bulk download. It contains tables such as:

```text
vendors.csv
sources.csv
artifacts.csv
observations.csv
candidate_sources.csv
unavailable_sources.csv
source_coverage.csv
```

Start with `vendors.csv`, use `source_coverage.csv` to identify available source types, and open `sources.csv` for the public URLs.

Candidate and unavailable records are operational metadata, not negative compliance or risk findings.

### `openva-inventory-template.csv`

A template for resolving your own vendor list. Supported identity columns include:

```text
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
```

At least one of `vendor_name`, `business_entity_name`, `domain`, or `registration_number` is required.

### `openva-sample-inventory.csv`

A small example showing the accepted inventory shape.

### Release manifests

```text
openva-release-downloads-manifest.json
release-artifacts.json
```

Use these when you need checksums, release identities, or artifact metadata.

## Resolve a private vendor inventory

The browser resolver processes CSV files locally in browser memory and does not upload the inventory to OpenVA.

For internal automation, use the local Python matcher, MCP server, or optional self-hosted match service inside your own environment.

OpenVA does not currently operate a production central matching service. The repository includes optional, API-key-gated verify transport for self-hosted use, disabled unless configured by the operator.

## Snapshot and freshness semantics

Generated packs may use deterministic timestamps, including fixed values such as `1970-01-01T00:00:00Z`. A pack-level generated timestamp is not evidence that every source was checked at that time.

For reproducibility and freshness, use:

- the release tag or repository commit SHA;
- source-level provenance timestamps;
- change-event timestamps;
- observation timestamps where available.

The static site displays loaded snapshot identity and source-health metadata when available. It is not a live monitoring feed.

## Licensing

- OpenVA software and project documentation: MIT.
- OpenVA-authored catalog metadata and generated data: CC0 1.0 Universal.
- Vendor documents, trademarks, pages, and other third-party materials: not licensed by OpenVA.

See `docs/licensing.md` for the precise boundary. OpenVA-authored CC0 metadata may be copied, modified, combined, redistributed, and used commercially without attribution or share-alike obligations.

## Coverage boundary

OpenVA v0.1.0 was an infrastructure launch with a seed dataset, not a completeness claim. Missing data does not mean a source does not exist, and a recorded source does not amount to vendor approval, legal advice, compliance advice, procurement advice, or a risk assessment.

To add or correct public-source metadata, use the vendor/source update issue pathway. Submit public URLs only; do not submit private agreements, authenticated portal exports, credentials, SOC reports, private certificates, screenshots, copied document text, or customer-specific terms.
