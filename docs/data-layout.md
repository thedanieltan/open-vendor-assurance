# Data Layout

OpenVA uses a predictable directory layout so records can be validated, indexed, exported, and consumed by downstream systems without relying on repository-specific assumptions.

## Canonical record layout

```text
data/
  vendors/
    {vendor_id}/
      vendor.yaml
      sources/
        {source_id}.yaml
      artifacts/
        {artifact_id}.yaml
      observations/
        {observation_id}.yaml
      changes/
        {change_id}.yaml
```

## Example fixtures

Example records live under:

```text
examples/vendors/{vendor_id}/...
```

Fixtures are for validation, tests, and documentation. They are not production vendor records.

## Generated indexes

Generated indexes live under:

```text
indexes/
  vendors.json
  sources.json
  artifacts.json
  observations.json
  changes.json
  summary.json
```

Indexes are derived files. Contributors must not edit them manually. Use the OpenVA tooling to regenerate them.

## Record identity

Record IDs must be stable, lowercase, hyphenated identifiers.

Examples:

```text
vendor_id: example-cloud
source_id: example-cloud-trust-center
artifact_id: example-cloud-trust-center
```

## Public-source rule

Production records must reference public sources only. If a record requires login, credentials, private portal access, customer status, NDA, sales approval, support ticket access, or anti-bot bypass, it is out of scope.
