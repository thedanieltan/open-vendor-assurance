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
| `received` | Request validated (limits only — no content digest); job created, request envelope stored, not yet enqueued |
| `queued` | Enqueued for the worker (queue carries `job_id` only) |
| `executing` | Worker re-read the request envelope and is running bounded SSRF-safe fetch/discovery |
| `completed` | Result written to the transient result store; `result_ref` set |
| `failed` | Terminal failure with a generic `error_code` |

## Transitions (actor-scoped)

Each edge names the actors permitted to perform it; every actor protocol below uses
**only** these edges. There is **no direct `received → executing` edge** — the
worker's recovery path is `received → queued → executing`.

```
received  → queued      [api (normal), reconciler (recovery), worker (recovery)]
received  → failed      [api]
queued    → executing   [worker]
executing → completed   [worker]
executing → failed      [worker (internal failure), watchdog (stale-lease / timeout)]
executing → queued      [watchdog (stale-lease takeover, re-dispatch)]
completed → (none)
failed    → (none)
```

There is **intentionally no `queued → failed` edge**: a `queued` record holds no
execution lease, so the watchdog (whose authority is **exactly** `executing → queued`
and `executing → failed`) has nothing to recover there, and a queued job only ever
leaves via `queued → executing`. Any other edge — or an actor not listed for an edge
— is rejected. This is the authoritative `transitions` map in the contract; a test
asserts every edge each actor protocol uses is present, that `received → executing`
is not a direct edge, and that the watchdog owns no edge beyond its two.

## Execution lease and crashed-worker recovery

The worker is the only actor that can leave `executing` on the happy path, so a
crashed worker must not strand a job. On winning `queued → executing` the worker
takes an **execution lease** (`lease_owner` + `lease_expires_at`, both required by
the schema while `executing`) and **heartbeats** to extend it. A **watchdog** (the
reconciler's `executing`-scoped role) owns recovery of a **stale** lease
(`lease_expires_at < now`): it CAS `executing → queued` to re-dispatch
(incrementing `attempt`) while `attempt < max`, else CAS `executing → failed`
(`execution_timeout`). A **live** lease is never preempted — a duplicate/redelivered
task whose record is `executing` with a live lease is **acked and dropped**; with an
expired lease it defers to the watchdog. This makes `execution_timeout → failed` and
bounded `attempt` retries performable by a live component even after the original
worker dies. (Drift test: worker wins `executing` → worker dies → lease expires →
exactly one component, the watchdog, recovers or terminalizes the job.)

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
client must present it to poll status and retrieve the result (the **same** rule for
both).

**Token transport (contract `result_access.token_transport`).** The capability
travels in a header **only** — `Authorization: Bearer <job_token>` — and **never in
a URL, query string, path, or redirect**, so it cannot leak via access/proxy logs,
browser history, or analytics. The Authorization header is **redacted/omitted** by
the API *and* the edge/reverse proxy; the raw token is never logged, traced,
metered, echoed in responses, or stored in plaintext — the record persists only its
SHA-256 digest `job_token_digest`. Verification uses a **constant-time** digest
comparison; a failed/absent token yields a **generic, content-free** response; CORS
does not expose the capability to unauthorized origins; browsers hold it
**in-memory for the session only** (not persistent storage). There is **no token
rotation/reissue in v1**. The token is listed in `prohibited_telemetry_fields`
(alongside `authorization_header`).

The result blob lives in the **transient result store** (`transient_result_store`),
referenced by `result_ref`, and is deleted on TTL/expiry.

## Idempotency (none in v1)

**There is no deduplication in v1.** Every request creates a **new job** (fresh
`job_id` + fresh `job_token`). There is **no content-derived dedup key** — a
SHA-256 of low-entropy vendor names/domains is dictionary-testable and must not
gate result access (deduping across callers on request content would let one
caller reach another caller's job/result).

An optional idempotency key is explicitly **deferred** to a later version and, if
added, must satisfy all of: bound to the request via a **server-keyed HMAC** (never
a plain content digest), scoped to an **authenticated caller namespace**, replay
(same key + same request) returns the existing job, conflict (same key + different
request) is rejected, and expiry + token-return are defined. None of that exists in
v1, so the schema carries no idempotency field.

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

The three independently-durable steps follow **one exact compare-and-set (CAS)
protocol with a single owner per transition** — not an assumed atomic op.

**Normal path (the API owns `received → queued`):**
1. API writes the request envelope.
2. API creates the job record in `received` (with `request_ref`).
3. API enqueues a task whose **name equals `job_id`**. Creating an existing task
   name returns `ALREADY_EXISTS`, which **dedups the API's own enqueue retry** — it
   is not a generic no-op, and a *completed/deleted* task name is tombstoned by
   Cloud Tasks for ~24h.
4. **After the enqueue is acknowledged,** the API does CAS `received → queued`.

**Worker:** on delivery, if the record is still `received` (the API crashed between
steps 3 and 4) it first does the recovery CAS `received → queued`, then CAS
`queued → executing` — using only declared edges (no direct `received → executing`).
Exactly one worker wins the CAS. It then does CAS `executing → completed | failed`.
A **duplicate delivery** whose CAS to `executing` fails (already executing/terminal)
is **acked and dropped**.

**Reconciler — recovery only.** It **never** owns the normal-path
`received → queued`. For a job stuck in `received` past a threshold: if the task is
still pending it sees `ALREADY_EXISTS` and leaves it; if the original task name is
tombstoned (completed/deleted), it re-enqueues with a **dispatch-generation-suffixed
task name** (`job_id-r{dispatch_attempt}`, e.g. `<uuid>-r1`) — a hyphen, never a
colon, because Cloud Tasks task IDs permit only `[A-Za-z0-9_-]`.

`dispatch_attempt` is a **separate counter from `attempt`**. `attempt` is the
watchdog's *execution*-retry counter and is pinned to `0` while `received` (no
watchdog runs on a non-executing job), so it can never advance a recovery name —
naming from it would regenerate the same `-r0` forever and strand the job behind the
~24h tombstone. The reconciler instead atomically increments `dispatch_attempt` (CAS;
concurrent reconcilers serialize, one wins per generation) **before** each re-enqueue,
so the first recovery is `-r1` (0 → 1, never the tombstoned `-r0`) and every
subsequent recovery (`-r2`, `-r3`, …) is a fresh, never-tombstoned name. Dispatch
recovery is **bounded** by a maximum generation; beyond it the reconciler stops
re-enqueueing and the job terminates by time-based expiry (`410` → `404`), so a stuck
job is neither stranded nor churning forever. The worker's CAS dedups any resulting
duplicate delivery.

**Crash points:**
- after envelope, before job create → orphan envelope (no job record; invisible to
  clients), TTL-reaped; API returns a generic retryable `503`, no `job_id` leaked;
- after job create, before enqueue → reconciler re-enqueues;
- after enqueue, before CAS `received → queued` → the worker recovers via CAS
  `received → queued` then `queued → executing`; a reconciler re-enqueue is deduped
  (`ALREADY_EXISTS`) or uses a dispatch-generation-suffixed name (`-r{dispatch_attempt}`)
  if tombstoned;
- worker crash while `executing` → execution timeout → `failed`, or expiry.

**Polling distinguishes** *accepted-but-not-dispatched* (`received`) from
*dispatched* (`queued`), so a client never mistakes an undispatched job for a lost
one.

## Data minimisation

The job record carries operational metadata only: `job_id`, `job_token_digest`,
`state`, `freshness_mode`, `request_ref`, `row_count`, `result_ref`, `error_code`,
`attempt`, `lease_owner`, `lease_expires_at`, timestamps, `expires_at`,
`not_advice`. It carries **no** uploaded inventory, vendor identity, request body,
content fingerprint, or dedup key —
enforced by `additionalProperties: false`. The result blob (referenced by
`result_ref`) is likewise transient and TTL-deleted and is never indexed by
submitted content.

## Expiry and deletion

Expiry is **time-based on `expires_at`, not a persisted state**, with explicit
**three-phase** HTTP semantics (the record holds `expires_at` and
`job_token_digest`, both gone once it is deleted, so a single "always 410" rule is
impossible):

- **pre-expiry** (`now < expires_at`, record present) → status/result, **`job_token`
  required**;
- **expired but retained** (`now >= expires_at`, record not yet physically deleted)
  → content-free **`410 Gone`**;
- **after physical deletion** (record gone) → content-free **`404 Not Found`** — the
  API can no longer authenticate or distinguish the id, and a 404 leaks nothing
  because `job_id` is not a credential and is indistinguishable from an unknown id.

Physical deletion removes three things, each by its store's native TTL plus an
object-lifecycle TTL backstop:

1. the durable **job record** (`result_ttl_hours_default: 24`);
2. the **transient request envelope** (deleted earlier, on the terminal
   transition, with the TTL only as a backstop);
3. the **transient result blob** (referenced by `result_ref`).

A separate result blob is **not** auto-deleted by the job-record TTL; its deletion
is driven by its own object-lifecycle rule (or a reaper), keyed to `expires_at`.
Nothing persists beyond the TTL except bounded aggregate metrics (counts,
durations) that contain no submitted content.

## Execution surface and platform limits (concrete)

The baseline worker is a **Cloud Run service handler invoked by Cloud Tasks**.
There is **no unbounded-runtime claim** — the platform limits are explicit: a Cloud
Tasks HTTP dispatch deadline of **30 min** and a Cloud Run service request timeout
of up to **60 min**, with a per-job execution timeout
(`baseline_per_job_budget_minutes` = 25 min) enforcing the ceiling.

**The hosted live-verify limit is grounded in the resolver's real fetch behaviour,
not in an assumed 500-row figure.** The resolver (`tools/openva/vendor_resolution.py`)
fetches with a **`SAFE_TIMEOUT_SECONDS` = 20 s** whole-request deadline, and per
source type it does **1 verify fetch + up to `max(len(_DISCOVERY_PATHS))` = 3
discovery-fallback fetches**, all **serial**; source types within a row are serial;
rows run at `verify_row_concurrency`. So `network_ops_per_source_type_worst = 4` and
`per_fetch_deadline_seconds = 20` are **imported from / asserted against the
resolver** by a drift test (it fails if the contract invents a lower timeout than
the resolver uses, or understates the per-source-type op bound).

The hosted limits (contract `hosted_verify_limits` + `verify_execution_budget`) are
therefore deliberately small and **distinct from the 500-row cached/batch limit**
(`limits.max_rows_cached`, which performs no live fetch):
`max_verify_rows 20`, `max_source_types_per_verify_row 4`, `verify_row_concurrency 10`.
Worst case = `ceil(20/10) × 4 × 4 × 20 s + 60 s = 700 s ≈ 11.7 min`, comfortably
**< the 25-min per-job budget < the 30-min dispatch deadline**. A drift test
recomputes this from the imported resolver constants so the row cap, fetch deadline,
op bound, concurrency, and budget cannot drift apart, and **fails if the hosted
limits could ever exceed the deadline**.

A **larger** verify limit is **not supported in v1** and is **not** achieved by a
hand-waved "scale-up path": it is a separate future work package that must fully
specify a parent/child decomposition (parent lifecycle, child work-item schema,
chunking, queue identity, child lease/attempt, aggregation, partial-failure,
terminalisation ownership, expiry coordination, and tests) before claiming any
larger bound.

## Component access and terminalization

Least-privilege access (contract `access_matrix`) is scoped to exactly the
operations each component performs:

- **API:** writes the envelope; creates/reads the job record **and CAS-owns only its
  edges** (`received → queued`, `received → failed`); **reads the result blob only
  after verifying a valid `job_token`** to serve it to the client. No result is ever
  readable without a valid `job_token`.
- **Worker:** reads the envelope, holds the execution lease, writes the result, CAS-
  owns `received → queued` (recovery) / `queued → executing` / `executing →
  completed | failed`, and deletes the envelope on terminalization.
- **Watchdog:** CAS-owns only the stale-lease recovery edges (`executing → queued`,
  `executing → failed`).
- **Candidate-ingress:** the **only** holder of the GitHub App key.

On success the worker terminalizes in this exact order: **write result blob → CAS
`executing → completed`** — and that single CAS **atomically sets `result_ref` and
clears `request_ref`, `error_code`, `lease_owner`, and `lease_expires_at` IN the job
record** (so the record is schema-valid the instant it is `completed`) — **→ delete
the physical request envelope** as a *separate* step (deleting the envelope is never
a substitute for clearing the `request_ref` pointer; a crash before the delete
leaves an orphan envelope reaped by its object-lifecycle TTL).

## Atomic transition mutations

Every transition that changes a field invariant is a **single compare-and-set on
the durable record** carrying the complete field payload, recorded machine-readably
in the contract `transition_mutations` and validated by a drift test that applies
each mutation to a source-state fixture and re-checks the schema:

| Transition (owner) | The CAS atomically sets |
| --- | --- |
| `received → queued` (api/reconciler/worker) | `state=queued`, `updated_at` (request_ref preserved; lease stays null) |
| `received → failed` (api) | `state=failed`, `error_code`, `request_ref=null`, `result_ref=null`, lease=null; then delete envelope |
| `queued → executing` (worker) | `state=executing`, `lease_owner`, `lease_expires_at`, `updated_at` (request_ref preserved) |
| `executing → completed` (worker) | `state=completed`, `result_ref`, `request_ref=null`, `error_code=null`, lease=null; then delete envelope |
| `executing → failed` (worker/watchdog) | `state=failed`, `error_code`, `request_ref=null`, `result_ref=null`, lease=null; then delete envelope |
| `executing → queued` (watchdog) | `state=queued`, `lease_owner=null`, `lease_expires_at=null`, `attempt=attempt+1`, `updated_at` (request_ref preserved for retry) |

A CAS is conditioned on the record version; a stale-version CAS fails and the actor
re-reads (so two actors never both win a transition).

## Concurrency and failure recovery

- Bounded concurrent jobs (`OPENVA_MAX_ACTIVE_JOBS`, enforced in the transport
  slice); over-limit requests are rejected (`rate_limited`).
- A crashed/abandoned job stays in `queued`/`executing` until either an execution
  timeout moves it to `failed` (`error_code: execution_timeout`) or it expires (then
  the three-phase `410`/`404` semantics apply). The client never hangs.
- Retries are bounded by `attempt` (max 10) and re-read the same request envelope;
  exhausted retries → `failed` with a generic `error_code`.
- No partial result is ever returned as `completed`.

## Limits and error codes

There are **two distinct limits**: the cached/batch enrich limit
`limits.max_rows_cached = 500` (no live fetch, no egress) and the hosted **live-verify**
limit `hosted_verify_limits.max_verify_rows = 20` (the job record's `row_count`
maximum matches *this*, since a job record exists only for verify mode).
**Over-limit requests are rejected by the API before a job is created**, so
`input_too_large` / `row_limit_exceeded` are **API rejection responses, not durable
job error codes**. The durable job `error_code` vocabulary is only:
`execution_timeout`, `upstream_unavailable`, `rate_limited`, `internal_error` —
stable, generic, content-free; upstream vendor messages and submitted content never
appear in an error.

## Non-advisory guarantee

Every job record and result carries `not_advice: true`; results are source-bound
metadata and observed state only — never a verdict, score, risk level, approval,
or suitability. Live results are labelled distinct from canonical catalogue truth.
