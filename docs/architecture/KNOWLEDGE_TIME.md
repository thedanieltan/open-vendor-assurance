# Assurance Record Knowledge Time

Operational metadata only. This document is not legal, compliance, procurement,
security, KYC, AML, audit, or vendor-risk advice.

## Purpose

Every assurance record in OpenVA carries an immutable `recorded_at` timestamp
that records when the record entered the repository's knowledge set.

## Semantics

`recorded_at` is repository knowledge time. It answers:

> When did OpenVA learn about this assurance?

It is explicitly not:

* issuance time, when the certification or report was granted;
* validity start, when the assurance becomes effective;
* observation time, when a source was checked;
* retrieval time, when data was fetched from an external system;
* Git commit time, when a file was committed.

## Invariants

1. Immutable: once an assurance record is admitted to the repository,
   `recorded_at` cannot be changed.
2. Explicit: the timestamp must be supplied explicitly. It cannot be inferred
   from file metadata, Git history, or other records.
3. Knowledge cutoff: projection includes a record only when
   `record.recorded_at <= knowledge_cutoff`.
4. Independent of instrument dates: instrument dates such as `valid_from`,
   `valid_until`, and `as_of_date` may precede or follow `recorded_at`.
5. UTC timestamps: timestamps use explicit timezone notation, for example
   `recorded_at: "2026-01-12T10:30:00Z"`.

## Schema Version

The addition of `recorded_at` as a required field changes the record contract.
Migrated fixtures use:

```yaml
schema_version: "0.1.1"
```

This records the migration without requiring a new `$id`.

## Bitemporal Projection

Knowledge time enables bitemporal projection, where OpenVA can answer:

* what was the state on a date, via `effective_at`;
* what could OpenVA have known on a date, via `knowledge_cutoff`.

These are different questions. A certificate might be withdrawn in January but
not recorded until February.

## Examples

Recent certification:

```yaml
assurance_id: acme-iso27001-2026
valid_from: "2026-01-10"
valid_until: "2027-01-09"
recorded_at: "2026-01-12T10:30:00Z"
```

Historical certification:

```yaml
assurance_id: legacy-soc2-2020
valid_from: "2020-01-01"
valid_until: "2021-01-01"
recorded_at: "2026-06-01T00:00:00Z"
```

Future projection:

```yaml
# Request
effective_at: "2026-01-15"
knowledge_cutoff: "2026-01-15"

# Record A
assurance_id: cert-a
valid_from: "2026-01-10"
valid_until: "2027-01-09"
recorded_at: "2026-01-12T10:30:00Z"

# Record B
assurance_id: cert-b
supersedes_assurance_id: cert-a
valid_from: "2027-01-10"
recorded_at: "2026-02-01T00:00:00Z"
```

At `knowledge_cutoff: 2026-01-15`, only Record A is known. Record B is
excluded because its `recorded_at` is after the cutoff.

## Testing

The repository includes structural tests that verify:

* assurance records have `recorded_at`;
* the timestamp is a valid ISO 8601 date-time with explicit timezone;
* the timestamp is not null;
* the timestamp is not date-only.
