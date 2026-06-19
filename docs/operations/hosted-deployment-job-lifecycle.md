# Hosted job/result lifecycle specification

The durable job/result lifecycle for the hosted `verify`-mode transport
([ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md),
governed by [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)).
Schema: [`schemas/openva/hosted-job-record.schema.json`](../../schemas/openva/hosted-job-record.schema.json).
Contract: [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Decision-only.** No job store is provisioned; this specifies the contract a
later transport slice (WP-02B) implements. Records are non-advisory and minimised.

## States

`received` → `queued` → `executing` → `completed` | `failed` → `expired`.
Terminal: `completed`, `failed`, `expired`.

| State | Meaning |
| --- | --- |
| `received` | Request validated (limits + digest); job created, not yet enqueued |
| `queued` | Enqueued for the worker |
| `executing` | Worker running bounded SSRF-safe fetch/discovery |
| `completed` | Result written; `result_ref` set |
| `failed` | Terminal failure with a generic `error_code` |
| `expired` | Job + result TTL-deleted (default 24h) |

## Transitions

```
received  → queued | failed
queued    → executing | failed | expired
executing → completed | failed
completed → expired
failed    → expired
expired   → (none)
```

Any other transition is rejected. The set is the authoritative `transitions` map
in the contract; a test asserts the doc, contract, and schema agree.

## Idempotency

Jobs are idempotent on `job_id`. The API computes `request_digest` (SHA-256 over
the canonical request) and, if an unexpired job with the same digest exists,
returns that `job_id` instead of creating a duplicate. The request itself is never
stored — only its digest.

## Data minimisation

The job record carries operational metadata only: `job_id`, `state`,
`freshness_mode`, `request_digest`, `row_count`, `result_ref`, `error_code`,
`attempt`, timestamps, `expires_at`, `not_advice`. It carries **no** uploaded
inventory, vendor identity, or request body — enforced by `additionalProperties:
false`. The result blob (referenced by `result_ref`) is likewise transient and
TTL-deleted and is never indexed by submitted content.

## Expiry and deletion

The store's native TTL (`result_ttl_hours_default: 24`) deletes both the job
record and the result blob at `expires_at`. Expiry is the only path out of the
terminal states; nothing persists beyond the TTL except bounded aggregate metrics
(counts, durations) that contain no submitted content.

## Concurrency and failure recovery

- Bounded concurrent jobs (`OPENVA_MAX_ACTIVE_JOBS`, enforced in the transport
  slice); over-limit requests are rejected (`rate_limited`).
- A crashed worker leaves a job in `queued`/`executing`; the TTL reaps it and the
  client sees `expired` rather than a hang.
- Retries are bounded by `attempt` (max 10); exhausted retries → `failed` with a
  generic `error_code` (`upstream_unavailable`, `execution_timeout`, …).
- No partial result is ever returned as `completed`.

## Error codes

Stable, generic, content-free: `input_too_large`, `row_limit_exceeded`,
`execution_timeout`, `upstream_unavailable`, `rate_limited`, `internal_error`.
Upstream vendor messages and submitted content never appear in an error.

## Non-advisory guarantee

Every job record and result carries `not_advice: true`; results are source-bound
metadata and observed state only — never a verdict, score, risk level, approval,
or suitability. Live results are labelled distinct from canonical catalogue truth.
