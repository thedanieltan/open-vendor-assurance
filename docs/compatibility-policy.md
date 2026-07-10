# Compatibility Policy

OpenVA compatibility is governed by explicit contracts and commit-addressed repository states, not by formal releases or version tags.

## Stable surfaces

Downstream consumers should treat these as the primary compatibility surfaces:

- `openva-pack.json`;
- schemas under `schemas/openva/`;
- generated indexes under `indexes/`;
- documented HTTP, MCP, adapter, and resolver result contracts;
- conformance fixtures;
- machine-readable manifest and digest fields.

## Catalog changes

Adding vendors, adding or correcting public source URLs, updating factual metadata, and rebuilding generated indexes are ordinary catalog changes. They publish continuously after acceptance and should not require consumer code changes when existing contracts remain valid.

## Compatibility-impacting changes

A change is compatibility-impacting when a conforming consumer must change its code or configuration to continue importing or using OpenVA. Examples include:

- removing or renaming a required field;
- changing required index or manifest keys;
- narrowing or changing enum semantics;
- changing matching or identity semantics incompatibly;
- changing required authentication or transport behavior;
- changing digest or canonicalisation rules;
- changing profile guarantees.

Such changes must include:

1. an explicit compatibility statement in the pull request;
2. updated schemas and conformance fixtures;
3. updated consumer documentation;
4. migration guidance where existing consumers must act;
5. validation proving the new contract is internally coherent.

## Pinning

Consumers that need controlled upgrades should pin:

```text
source commit SHA
schema version
profile or pack identifier
pack or manifest digest
```

A timestamp alone is not a compatibility identifier. A branch name such as `main` means “follow the latest accepted state” and is appropriate only for consumers that deliberately choose continuous updates.

## Deprecation

Where practical, incompatible fields or behaviors should be deprecated before removal. Deprecation documentation should identify:

- the old surface;
- the replacement surface;
- deterministic mirror or translation behavior, when provided;
- the removal condition;
- the migration path.

## No release-number dependency

OpenVA may retain internal package or schema version fields where a protocol requires them, but those identifiers do not create a formal catalog-release lifecycle. Publication authority remains the accepted state of `main`, and reproducibility remains commit-addressed.
