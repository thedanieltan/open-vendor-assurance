# Reviewed Candidate Promotion Convention

Candidate sources are discovery outputs. They are not canonical catalog sources.

Use this action name for candidate promotion planning:

```text
promote_candidate_source_for_review
```

The action means the candidate is eligible for maintainer review. It does not promote the candidate by itself.

Required action posture:

```text
requires_human_review: true
writes_canonical_sources: false
non_advisory: true
```

Expected review evidence:

```text
candidate_source_id
candidate_url
vendor_id
source_type
evidence.confidence
evidence.http_status
evidence.matched_terms
evidence.page_title
path
```

Promotion planning may propose reviewed candidate promotion actions. A separate reviewed apply workflow is required before any candidate can become a canonical source record.

Guardrails:

- no candidate auto-promotion
- no raw vendor document mirroring
- no gated, private, customer-only, or authenticated-only sources
- no vendor approval or suitability conclusion
- no automatic merge
