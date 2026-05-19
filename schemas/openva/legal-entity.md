# Legal Entity Records

OpenVA legal entity records are evidence-backed identity records. They describe public entity metadata observed from public sources at a point in time.

They are not current corporate registry attestations. OpenVA does not verify that an entity currently exists, is active, is solvent, remains registered, or is the correct counterparty for a specific customer relationship.

## Evidence Model

`legal_entity` records link to existing OpenVA `source`, `artifact`, and `source_observation` records. The entity record stores identity fields and source IDs; sources and observations carry provenance, access metadata, hashes, and freshness observations.

`catalog_status: canonical` means the record has at least one public verification source. It does not mean OpenVA has verified current legal status.

`catalog_status: stub` means the record is not eligible for contracting-entity resolution indexes.

## Lifecycle Events

`lifecycle_events` are optional source-backed facts. Absence of lifecycle events means no lifecycle evidence has been recorded by OpenVA. It does not mean the entity is currently active or unchanged.

Consumers must perform their own current-status verification before using entity metadata for operational, legal, procurement, compliance, security, KYC, AML, sanctions, regulatory, or vendor-risk decisions.
