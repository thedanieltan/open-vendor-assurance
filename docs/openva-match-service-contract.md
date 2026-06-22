# OpenVA Match Service Contract

The OpenVA match service is an optional self-hosted HTTP wrapper around the OpenVA pack reader and vendor inventory matcher. It returns public metadata references only. It does not make risk, compliance, approval, or suitability assertions.

OpenVA does not currently operate a production central matching service or a hosted private-inventory upload service. The repository now ships an optional, API-key-gated verify transport for self-hosted use and future hosted deployment. The transport is disabled by default, and this release does not include the durable backend, worker, production infrastructure, or public verify endpoint required for an operated hosted service. Until those later deployment gates are completed, private vendor inventories should remain browser-local, local, or inside a consumer-controlled self-hosted environment. Consumers that want HTTP access run their own service instance from a pinned repository commit or release.

## Startup

The service loads `OPENVA_PACK_PATH` at process startup and fails fast if the pack is missing or invalid. Pack freshness is controlled by rebuilding/redeploying the service with a new pack and restarting the process. There is no hot reload, cache invalidation endpoint, tenant state, persistence, or writeback.

FastAPI and Uvicorn are service-only dependencies declared in `services/openva_match_service/pyproject.toml`; they are not dependencies of the root OpenVA package, validator, pack reader, or adapters.

## Authentication

Set `OPENVA_SERVICE_API_KEY`. Requests must include:

```http
Authorization: Bearer <key>
```

Missing or invalid keys return `401`.

## Headers

Every response, including errors, includes:

- `X-OpenVA-Service-Version`
- `X-OpenVA-Pack-Profile`
- `X-OpenVA-Pack-Schema-Version`
- `X-OpenVA-Pack-Generated-At`
- `X-OpenVA-Advisory-Boundary: non_advisory`

`X-OpenVA-Pack-Generated-At` mirrors pack metadata. When deterministic builds
use a fixed timestamp such as `1970-01-01T00:00:00Z`, this header is not a
catalog freshness signal.

## `GET /healthz` and `GET /readyz`

Unauthenticated probes for orchestrators. `GET /healthz` returns `200 {"status": "ok"}` while the process is up. `GET /readyz` returns `200 {"status": "ready"}` once the pack/matcher state is loaded and `503 {"status": "not_ready"}` otherwise. Both responses still carry the `X-OpenVA-*` headers.

## Request limits

`POST /match` is bounded by configurable limits (defaults `OPENVA_MAX_UPLOAD_BYTES=5000000`, `OPENVA_MAX_ROWS=500`). An upload larger than `OPENVA_MAX_UPLOAD_BYTES` is rejected with `413` and the stable `http_error` shape; an inventory with more than `OPENVA_MAX_ROWS` rows is rejected with `400`. The cached `/match` and `/v1` read path is synchronous with no persistence. The optional, flag-gated verify transport adds an async job lifecycle: `OPENVA_JOB_TTL_HOURS` is enforced (the verify job `expires_at`, plus a retained-window purge that physically deletes the record), while `OPENVA_MAX_ACTIVE_JOBS` remains reserved and unenforced (verify concurrency control is deferred to the worker, WP-02C).

## Verify transport (async, WP-02A)

A hosted **verify** transport is available behind the `OPENVA_VERIFY_TRANSPORT_ENABLED`
feature flag. It is **off by default**: when off, both verify endpoints return `404`
(the rollback posture). Disabling the flag does not change the existing cached-endpoint
behaviour or the loaded app state; the verify routes are still *registered* (so they
appear on the OpenAPI surface) but return `404` until the flag is enabled. Enabling it
adds the verify behaviour only — it does not change any existing endpoint.

Unlike the cached path (synchronous, no persistence, no source fetch), verify mode is an
**async job** model: it acknowledges that verify introduces durable jobs and, in a later
slice, live source egress (the resolver worker) per
[ADR-0001](architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md) and
the [hosted-deployment contract](operations/contracts/hosted-deployment.yaml). **WP-02A
ships the transport and API contract only — there is no worker, no queue, and no durable
backend in this slice.** A created job therefore stays in state `received` and never
executes; that is the correct behaviour for this slice. The in-memory stores are
non-durable scaffolding that WP-02B replaces with the durable backend.

**Job model.** A verify job moves through `received` → `queued` → `executing` →
`completed` | `failed` (`completed`/`failed` are terminal). In WP-02A only `received` is
ever reached. The durable record is operational metadata only: it carries no submitted
inventory content, no vendor identity strings, and no request bodies. In WP-02A the
submitted rows are NOT retained at all — they are validated then discarded, and the
transient request envelope holds only minimised metadata (`row_count`); the durable,
encrypted, TTL-deleted envelope holding the actual submitted input arrives in WP-02B. See
[`schemas/openva/hosted-job-record.schema.json`](../schemas/openva/hosted-job-record.schema.json).

**Submission access.** `POST /v1/verify` **always** requires the bearer API key, even when
`OPENVA_PUBLIC_READ_ENABLED=true`. Public-read mode grants read-only access to the cached
`/v1` data endpoints only; it never enables verify submission. The poll endpoint
(`GET /v1/verify/{job_id}`) is authorized **solely** by the `job_token`, not the API key.

**Token transport (capability).** Job creation returns a high-entropy `job_token`
**once**. Polling/retrieval requires that token, carried **only** in the
`Authorization: Bearer <job_token>` header — never in a query string, URL path, cookie,
or redirect. `job_id` is a loggable correlation id, not a credential. The raw token is
**never logged and never stored**; only its SHA-256 digest (`job_token_digest`) persists,
and comparison is **constant-time**. The poll endpoint resolves the lifecycle in order:
`404` for an unknown/deleted (or non-UUID) `job_id` (checked first; `job_id` is not a
credential so it leaks nothing), `410` for an expired-but-retained job (checked before the
token), `401` for a missing/invalid `job_token` on a live job (generic, no token echo),
and `200` otherwise. The `401`, `404`, and `410` responses are all **content-free** (an
empty body) — they carry the `X-OpenVA-*` and `X-OpenVA-Advisory-Boundary: non_advisory`
headers but no JSON. `not_advice: true` appears in the body of **successful** payloads
only (creation and the `200` poll); every response, including the content-free errors,
still carries the advisory-boundary header. The expired-but-retained `410` window is
bounded: after it elapses the record (with its `expires_at` + `job_token_digest`) is
physically deleted, so a later poll is a content-free `404`.

**Limit.** Verify requests are bounded by `OPENVA_MAX_VERIFY_ROWS` (default and
authoritative maximum `20`, aligned to the hosted-deployment contract's
`hosted_verify_limits.max_verify_rows`; a configured value above it fails closed at
startup). `source_types` is bounded to `4` (the grounded verify budget, aligned to
`hosted_verify_limits.max_source_types_per_verify_row`). These are far smaller than the
cached `OPENVA_MAX_ROWS` cap because each verify row would drive real, serial, SSRF-safe
live fetches in the later worker slice. An over-`rows` request is rejected by the API with
`413` and the stable `row_limit_exceeded` code **before any job is created** — a pre-job
rejection, never a job failure code; too many `source_types` returns `422`. Verify rows
accept vendor **identities only**; a fetch-target URL field is rejected with `422`.
Concurrency/abuse control is deferred to the worker (WP-02C) and edge rate limiting
(WP-02H) — WP-02A enforces no per-instance active-job cap.

## `GET /pack/meta`

Returns pack metadata:

```json
{
  "profile_id": "openva.public-metadata.v1",
  "schema_version": "openva-export-pack.v1",
  "generated_at": "1970-01-01T00:00:00Z",
  "counts": {
    "vendors": 143,
    "sources": 582,
    "candidate_sources": 0,
    "unavailable_sources": 16
  },
  "non_advisory": true
}
```

## `POST /match`

Version 1 accepts CSV only as multipart form field `inventory_csv`.

Minimum input columns: include at least one of `vendor_name`, `business_entity_name`, `domain`, or `registration_number`.

```csv
vendor_name,business_entity_name,domain,jurisdiction,registration_number,registered_address
Stripe,,stripe.com,SG,,
,Slack Technologies LLC,,,,
```

Response:

```json
{
  "meta": {
    "profile_id": "openva.public-metadata.v1",
    "schema_version": "openva-export-pack.v1",
    "generated_at": "1970-01-01T00:00:00Z",
    "counts": {
      "vendors": 143,
      "sources": 582,
      "candidate_sources": 0,
      "unavailable_sources": 16
    },
    "non_advisory": true,
    "service_version": "0.1.0",
    "advisory_boundary": "non_advisory"
  },
  "rows": []
}
```

The service preserves original CSV fields as strings. Matcher fields are converted from CSV cells to native JSON types. `_json` suffixes from the CSV adapter are removed in service responses, including `primary_source_by_type_json` becoming `primary_source_by_type`.

Brand matching and legal entity resolution are separate. `matched_vendor_id`, `matched_display_name`, `match_method`, and `match_confidence` describe the vendor or brand match. `legal_entity_match_method` and `legal_entity_resolution_confidence` describe entity-level resolution when OpenVA has source-backed legal entity metadata.

For a Singapore row such as `Stripe,,stripe.com,SG,,`, OpenVA may return `legal_entity_match_method: "jurisdiction_resolution_index"` and `legal_entity_resolution_confidence: "candidate"` if the contracting-entity resolution index has a Singapore candidate. `candidate` means public metadata suggests the entity may be relevant for that jurisdiction. It is not derived from the user's signed agreement.

OpenVA provides public DPA references only. Consumers should present a static reminder near DPA evidence telling users to confirm that their signed agreement names the expected contracting entity.

## Tier-aware response fields

Every match row includes:

- `record_class`
- `canonical`
- `catalog_tier`
- `review_state`
- `advisory_boundary`

These fields describe the OpenVA metadata and service response boundary only.
They do not describe whether the user's vendor relationship is approved,
compliant, low-risk, high-risk, suitable, contractually verified, KYC/AML
cleared, sanctions cleared, or legally adequate.

Inventory match rows are transient matching results. They are not canonical
OpenVA source records. A match row may report `catalog_tier: human_reviewed`
only to indicate that the underlying OpenVA metadata used for matching came
from human-reviewed catalog records.

Nested `canonical_sources` and `primary_source_by_type` entries should preserve
their own source-level tier annotations so consumers can distinguish reviewed
canonical records from future candidate, observation, or machine-validated
records.

## Downstream consumer guidance

Consumers should preserve `catalog_tier`, `review_state`, `record_class`,
`canonical`, and `advisory_boundary` when importing OpenVA outputs.

Future observation and machine-validation records must remain visually and
semantically distinct from human-reviewed canonical source records.

Consumers must not infer vendor approval, compliance status, risk level,
procurement suitability, contracting-entity verification, KYC/AML status,
sanctions status, legal advice, or operational adequacy from these fields.

## Consumer Migration Notes

Downstream consumers should replace local `OPENVA_PACK_PATH` invocation with `OPENVA_SERVICE_URL` and `OPENVA_SERVICE_API_KEY`, send uploaded inventory CSV files to `POST /match`, and consume matcher fields as native JSON arrays and objects instead of JSON-encoded CSV cell strings.
