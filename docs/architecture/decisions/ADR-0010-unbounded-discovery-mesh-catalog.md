# ADR-0010: Unbounded discovery-mesh catalog

## Status

Accepted

## Decision

OpenVA does not impose a maximum vendor-count ceiling on its catalog or discovery queue.

Deterministic shards partition execution without excluding vendors. Per-vendor network budgets remain mandatory because they protect third-party infrastructure and OpenVA's own workers; they are not catalog capacity limits.

An optional operator-supplied vendor limit may be used only for diagnostics, recovery, or incident response. Scheduled production execution processes the full eligible catalog over all configured shards.

## Consequences

- catalog breadth may grow to thousands or millions of candidate identities;
- scaling is handled through sharding, deduplication, backpressure, retry scheduling, and provider yield;
- source and identity admission remain evidence-controlled;
- canonical mutations remain isolated and reversible;
- no numeric crawler page budget may be represented as a vendor-catalog cap.

This decision is operational and non-advisory.
