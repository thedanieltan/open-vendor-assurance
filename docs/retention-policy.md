# Retention Policy

OpenVA is not a permanent archive of vendor legal, privacy, security, or assurance documents.

The project preserves current public-source metadata, source locations, source access classification, rights classification, provenance metadata, hashes, and factual change history.

## Default retention

- Current vendor metadata: indefinite
- Current artifact metadata: indefinite
- Change summaries: indefinite
- Observation manifests: 24 months
- Extracted public text, where permitted: 12 months
- Screenshots, where permitted: 6 months
- Failed fetch logs: 90 days
- Raw documents: not stored by default

## Raw document rule

Raw source documents must not be committed by default.

If a raw source is ever retained, it requires explicit rights classification, maintainer approval, and a retention period.

## Trimming rule

Maintainers may trim old observation files once the retention period expires, provided that current metadata and historical change summaries remain intact.
