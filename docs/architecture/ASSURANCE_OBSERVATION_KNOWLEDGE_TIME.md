# Assurance Observation Knowledge Time

Operational metadata only. This document is not legal, compliance,
procurement, security, KYC, AML, audit, or vendor-risk advice.

## Purpose

Every assurance observation carries an immutable `recorded_at` timestamp that
records when the observation entered OpenVA's repository knowledge set.

## Semantics

`observed_at` records when the underlying fact or public evidence was observed.
It remains the observation time of the source fact.

`recorded_at` records when OpenVA learned and committed the immutable
observation to its repository knowledge set. It is repository knowledge time.

The two timestamps answer different questions:

* `observed_at`: when was the evidence observed?
* `recorded_at`: when did OpenVA know this observation?

Future verification-state admission uses:

```text
observation.recorded_at <= knowledge_cutoff
```

## Invariants

1. Immutable: once an assurance observation is admitted to the repository,
   `recorded_at` cannot be changed.
2. Explicit: the timestamp must be supplied explicitly. It cannot be inferred
   from file metadata, Git history, the system clock, or `observed_at`.
3. Timezone-bearing: timestamps must include `Z` or a numeric UTC offset, for
   example `2026-01-20T00:00:00Z` or `2026-01-20T08:00:00+08:00`.
4. Non-advisory: knowledge time records repository admission only. It does not
   state that an assurance is compliant, current, adequate, or verified.

## Ordering

This migration does not enforce `observed_at <= recorded_at` structurally. The
existing observation model distinguishes when evidence was observed from when
OpenVA recorded the observation, but it does not yet define a universal ordering
rule for every future observation producer and backfill scenario.

Synthetic fixtures choose deterministic `recorded_at` values that are at or
after their stated `observed_at` when that is appropriate for the scenario.

## Schema Version

The addition of `recorded_at` as a required assurance-observation field changes
the observation contract. Migrated synthetic fixtures use:

```yaml
schema_version: "0.1.1"
```

This follows the existing pre-1.0 schema-version pattern without changing the
schema `$id`.
