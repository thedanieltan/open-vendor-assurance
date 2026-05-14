# Export Profile Contract

OpenVA publishes a consumer-neutral public metadata export pack.

The current export profile is:

```json
{
  "profileId": "openva.public-metadata.v1",
  "schemaVersion": "openva-export-pack.v1"
}
```

## Meaning

`profileId` identifies the semantic profile of the pack.

`openva.public-metadata.v1` means:

- public-source-only records;
- metadata-first records;
- no raw document mirroring by default;
- non-advisory content;
- vendor, source, artifact, observation, change, and summary indexes;
- downstream consumers own their own operational interpretation.

`schemaVersion` identifies the export pack envelope shape.

`openva-export-pack.v1` means the pack manifest contains explicit export contract fields, index paths, license metadata, and guarantees.

## Transition aliases

During the 0.1 development line, OpenVA also keeps the earlier snake_case fields:

```json
{
  "pack_id": "open-vendor-assurance",
  "schema_version": "0.1.0",
  "generated_at": "1970-01-01T00:00:00Z"
}
```

The camelCase fields are the consumer-facing export contract. The snake_case fields remain compatibility aliases until a later breaking version.

## Consumer rule

Consumers should check:

- `profileId`;
- `schemaVersion`;
- `guarantees`;
- index existence;
- index counts;
- summary counts;
- deterministic pack digest.

Consumers must not treat OpenVA records as vendor approval, legal advice, compliance advice, procurement advice, security advice, KYC advice, AML advice, or risk scoring.
