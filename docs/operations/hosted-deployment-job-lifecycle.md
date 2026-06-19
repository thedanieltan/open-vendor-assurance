# Hosted job/result lifecycle specification

The durable job/result lifecycle for the hosted `verify`-mode transport
([ADR-0006](../architecture/decisions/ADR-0006-hosted-public-read-deployment.md),
governed by [ADR-0001](../architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md)).
Schema: [`schemas/openva/hosted-job-record.schema.json`](../../schemas/openva/hosted-job-record.schema.json).
Contract: [`contracts/hosted-deployment.yaml`](contracts/hosted-deployment.yaml).

**Decision-only.** No job store is provisioned; this specifies the contract a
later transport slice (WP-02B) implements. Records are non-advisory and minimised.

## States

`received` → `queued` → `executing` → `completed` | `failed`.
Terminal: `completed`, `failed`. **Expiry is not a state** (see *Expiry and
deletion*); it is time-based on `expires_at`.

| State | Meaning |
| --- | --- |
| `received` | Request validated (limits + digest); job created, request envelope stored, not yet enqueued |
| `queued` | Enqueued for the worker (queue carries `job_id` only) |
| `executing` | Worker re-read the request envelope and is running bounded SSRF-safe fetch/discovery |
| `completed` | Result written to the transient result store; `result_ref` set |
| `failed` | Terminal failure with a generic `error_code` |

## Transitions

```
received  → queued | failed
queued    → executing | failed
executing → completed | failed
completed → (none)
failed    → (none)
```

Any other transition is rejected. The set is the authoritative `transitions` map
in the contract; a test asserts the doc, contract, and schema agree.

## Transient request envelope (how the worker gets the request)

The submitted input (vendor identities / batch rows) is **not** carried in the
queue and **not** stored in the durable job record (which holds only a
`request_ref` pointer and minimised metadata). At `received`, the API writes the
input to a **transient request store** (`transient_request_store`) — a separate,
encrypted-at-rest object keyed by `job_id` and referenced by `request_ref` — and
enqueues only the `job_id`.
The worker, at `executing`, reads the envelope by `job_id` using **workload
identity** (least privilege: API writes, worker reads; no static credentials).

The envelope is bounded by the existing upload/row caps (`OPENVA_MAX_UPLOAD_BYTES`,
`OPENVA_MAX_ROWS`); over-cap requests are rejected at the API before any job is
created. The envelope is deleted on completion, failure, or abandonment, with an
object-lifecycle TTL (≤ the job TTL) as a backstop. On a bounded retry the worker
re-reads the same envelope (it is not deleted until the job is terminal). This is
the central asynchronous data path; the Cloud Tasks payload is deliberately **not**
used to carry inventory (task payloads are durably stored and size-limited).

## Result access (authorization)

`job_id` is a loggable correlation id and is **not** an access credential. At
creation the API returns a single high-entropy **`job_token`** capability; the
client must present it to poll status and retrieve the result. The token is never
logged (it is in `prohibited_telemetry_fields`) and never stored in plaintext —
the record persists only its SHA-256 digest, `job_token_digest`, for verification.
The result blob lives in the **transient result store** (`transient_result_store`),
referenced by `result_ref`, and is deleted on TTL/expiry.

## Idempotency (no content-based deduplication)

There is **no content-derived dedup key.** A SHA-256 of low-entropy vendor
names/domains is dictionary-testable and must not gate result access — deduping
across callers on request content would let one caller reach another caller's
job/result. So:

- **Default:** every request creates a **new job** (fresh `job_id` + fresh
  `job_token`).
- **Optional:** a client may supply a **high-entropy idempotency key** scoped to
  its own calling capability; the API stores only its digest (`idempotency_key_digest`)
  and dedups **only that caller's own retries** — returning the existing job (and a
  capability) **only to a caller presenting the matching key**, which the original
  caller holds. It never dedups across callers and never mints a capability for an
  existing job to a different caller.

If a content fingerprint is ever needed for diagnostics it must be a keyed HMAC
with a defined scope, never a plain content digest, and never an identity or
access key.

## State invariants (schema-enforced)

The job schema (`hosted-job-record.schema.json`) enforces the state-dependent
invariants with `if`/`then`/`allOf`, not just field shapes — invalid records fail
validation:

- `received` / `queued` / `executing`: `request_ref` present (live envelope),
  `result_ref` null, `error_code` null;
- `completed`: `result_ref` present, `request_ref` null (envelope deleted),
  `error_code` null;
- `failed`: `error_code` present (generic), `request_ref` null, `result_ref` null;
- `freshness_mode` is `verify` for every record (cached mode is synchronous and
  creates no job).

## Consistency and recovery (envelope → job → queue handoff)

The three durable steps are made recoverable, not assumed atomic:

1. write the request envelope → 2. create the job record in `received` (with
`request_ref`) → 3. enqueue the `job_id`.

- **Enqueue is idempotent:** the queue task name equals `job_id`, so a retry/
  re-enqueue is a no-op (no duplicate dispatch).
- **Reconciler (outbox):** a job left in `received` past a short threshold is
  re-enqueued by a reconciler that **owns the `received → queued` transition**;
  this recovers a crash between steps 2 and 3.
- **Compare-and-set transitions:** every transition advances only from its
  expected prior state; the worker owns `executing → completed|failed`.
- **Orphan envelope:** an envelope written when step 2 then fails has no job record
  (so it is invisible to clients) and is removed by its object-lifecycle TTL; the
  API returns a generic retryable `503` and leaks no `job_id`.
- **Polling distinguishes** *accepted-but-not-dispatched* (`received`) from
  *dispatched* (`queued`), so a client never mistakes an undispatched job for a
  lost one.

## Data minimisation

The job record carries operational metadata only: `job_id`, `job_token_digest`,
`idempotency_key_digest` (optional), `state`, `freshness_mode`, `request_ref`,
`row_count`, `result_ref`, `error_code`, `attempt`, timestamps, `expires_at`,
`not_advice`. It carries **no** uploaded inventory, vendor identity, request body,
or content fingerprint — enforced by `additionalProperties: false`. The result blob
(referenced by `result_ref`) is likewise transient and TTL-deleted and is never
indexed by submitted content.

## Expiry and deletion

Expiry is **time-based on `expires_at`, not a persisted state**. Once
`now >= expires_at`, the API returns a content-free **`410 Gone`** for that
`job_id` — regardless of whether physical deletion has happened yet — so behaviour
is well defined even though store TTL deletion is asynchronous and not
instantaneous. Physical deletion removes three things, each by its store's native
TTL plus an object-lifecycle TTL backstop:

1. the durable **job record** (`result_ttl_hours_default: 24`);
2. the **transient request envelope** (deleted earlier, on the terminal
   transition, with the TTL only as a backstop);
3. the **transient result blob** (referenced by `result_ref`).

A separate result blob is **not** auto-deleted by the job-record TTL; its deletion
is driven by its own object-lifecycle rule (or a reaper), keyed to `expires_at`.
Nothing persists beyond the TTL except bounded aggregate metrics (counts,
durations) that contain no submitted content.

## Concurrency and failure recovery

- Bounded concurrent jobs (`OPENVA_MAX_ACTIVE_JOBS`, enforced in the transport
  slice); over-limit requests are rejected (`rate_limited`).
- A crashed/abandoned job stays in `queued`/`executing` until either an execution
  timeout moves it to `failed` (`error_code: execution_timeout`) or, if it never
  reaches a terminal state, it expires: after `expires_at` the API returns
  `410 Gone` and the record + envelope + result are deleted. The client never
  hangs.
- Retries are bounded by `attempt` (max 10) and re-read the same request envelope;
  exhausted retries → `failed` with a generic `error_code`
  (`upstream_unavailable`, `execution_timeout`, …).
- No partial result is ever returned as `completed`.

## Error codes

Stable, generic, content-free: `input_too_large`, `row_limit_exceeded`,
`execution_timeout`, `upstream_unavailable`, `rate_limited`, `internal_error`.
Upstream vendor messages and submitted content never appear in an error.

## Non-advisory guarantee

Every job record and result carries `not_advice: true`; results are source-bound
metadata and observed state only — never a verdict, score, risk level, approval,
or suitability. Live results are labelled distinct from canonical catalogue truth.
