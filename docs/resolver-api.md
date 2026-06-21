# OpenVA zero-install enrichment API (`/v1`)

The `/v1` API extends the [OpenVA match service](../services/openva_match_service/) so
spreadsheet and document integrations can enrich a vendor register with current public
source references **without cloning the repository, installing Python, or running
Docker**.

This is **cached catalogue enrichment**: responses reflect the published catalogue pack
loaded by the service at startup. **No source URL is fetched or verified live during a
request.** Output is non-advisory metadata — every response carries `not_advice: true`
and the `X-OpenVA-Advisory-Boundary: non_advisory` header. It is not compliance approval,
vendor-risk assessment, legal advice, procurement approval, or security certification.

## What is sent and returned

You send vendor identities (name and/or domain, optionally business-entity name or
registration number). OpenVA resolves each against the loaded catalogue and returns the
matched vendor's **canonical** public source references plus snapshot provenance. Only
vendor-identity fields and your selected source types are sent; nothing is persisted.

## Access

Endpoints require `Authorization: Bearer <OPENVA_SERVICE_API_KEY>` unless the deployment
sets `OPENVA_PUBLIC_READ_ENABLED=true`, which makes the `/v1` read-only endpoints public.
Public mode grants read-only catalogue access only. **Do not embed an API key in
spreadsheet or Office add-in client code.**

## Endpoints

### `GET /v1/catalog/meta`
Returns the `snapshot` identity and the pack's `guarantees` (`public_sources_only`,
`metadata_first`, `non_advisory`, `raw_documents_mirrored_by_default`).

### `GET /v1/vendors/{vendor_id}`
Returns `{ vendor, canonical_sources, snapshot, not_advice }`. Unknown or unsafe vendor
ids return `404`. Only canonical sources are listed; internal pack paths are never
exposed.

### `GET /v1/vendors/{vendor_id}/sources?source_type=dpa&source_type=privacy_notice`
Returns canonical sources, optionally filtered by repeatable `source_type`. Omitting
`source_type` returns all canonical sources. An unknown source-type string yields an
empty filtered result.

### `POST /v1/match`
Resolve one identity. At least one of `vendor_name`, `domain`, `business_entity_name`,
`registration_number` must be non-empty.

```json
{ "vendor_name": "Stripe", "domain": "stripe.com" }
```

Response `match` carries the authoritative state and is never reinterpreted:

| `status` | Meaning |
|---|---|
| `matched` | A single confident catalogue vendor. `method`/`confidence`/`vendor_id` populated. |
| `ambiguous` | Multiple plausible vendors; **not** collapsed into a match. `candidates` listed; no sources returned. |
| `no_match` | No catalogue vendor. No sources returned. |

### `POST /v1/enrich`
The batch enrichment endpoint. It is consumed primarily by **agents** composing OpenVA
with their own workspace connectors (the agent-composed primary distribution path —
see [`agent-workspace-composition.md`](agent-workspace-composition.md)), and also by the
secondary native/reference clients. The MCP `enrich_inventory` tool delegates to the same
shared enrichment authority as this endpoint, so the two surfaces agree.
This HTTP endpoint carries the rows under a **`vendors`** array; the MCP
`enrich_inventory` tool carries the **same** shared rows
([`schemas/openva/agent-enrichment-row.schema.json`](../schemas/openva/agent-enrichment-row.schema.json))
under a `rows` array instead — a deliberate, documented adapter mapping, not one wire
schema for both surfaces.

`vendors` is required and non-empty (bounded
by `OPENVA_MAX_ROWS`; exceeding it returns `413`). `source_types` is optional (omitted =
all canonical types). Rows are processed in input order; duplicates are preserved;
`row_id` (string or integer) is echoed back exactly. The whole JSON body is also bounded
by `OPENVA_MAX_REQUEST_BYTES` (enforced before parsing; over-limit returns `413`), with
per-field length and array-size caps as defense in depth (over-limit returns `422`).

```json
{
  "vendors": [{ "row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com" }],
  "source_types": ["dpa", "subprocessors_list", "privacy_notice", "security_page", "trust_center", "compliance_page"]
}
```

Each result includes `match`, canonical `sources`, `primary_source_by_type` (the
matcher's existing primary choice per type), `source_urls_by_type`, machine-state
`notes`, and a stable `spreadsheet` projection for write-back:

| Spreadsheet key | Source |
|---|---|
| `openva_match_status` / `openva_vendor_id` / `openva_vendor_name` | match result |
| `openva_dpa` | `dpa` primary source URL |
| `openva_subprocessors` | `subprocessors_list` |
| `openva_privacy_notice` | `privacy_notice` |
| `openva_security` | `security_page` |
| `openva_trust_center` | `trust_center` |
| `openva_compliance` | `compliance_page` |
| `openva_last_observed_at` | latest per-source observation, or `null` |
| `openva_snapshot_digest` | snapshot digest |
| `openva_notes` | machine-state notes |

Missing source types, ambiguous, and no-match rows return `null` source columns. Notes
explain machine states only (e.g. `Ambiguous vendor match`, `No catalogue match`,
`Matched vendor has no canonical DPA source`) — never a compliance conclusion, and
absence is never labelled non-compliance.

## Verify transport (`/v1/verify`, WP-02A)

The endpoints above are **cached** catalogue enrichment: synchronous, no persistence, and
no live source fetch. A separate **verify** transport adds an async job model behind the
`OPENVA_VERIFY_TRANSPORT_ENABLED` feature flag (**off by default**). When the flag is off
both verify endpoints return `404` and the service is cached-only (the rollback posture).
WP-02A ships the **transport and API contract only** — there is no worker yet, so a
created job stays in state `received` and never executes. Verify mode acknowledges that it
introduces async jobs (persistence) and, in a later slice, live source egress (the
worker) per [ADR-0001](architecture/decisions/ADR-0001-hosted-resolver-and-live-verification.md).

### `POST /v1/verify`
Create a verify job. Subject to the same public-read-or-API-key access policy as the other
`/v1` endpoints. The body carries rows under a **`rows`** array; each row is a vendor
**identity** (at least one of `vendor_name`, `domain`, `business_entity_name`,
`registration_number`), optionally with a `row_id` and an optional top-level
`source_types`. Rows accept identities only — a `url`/`candidate_url`/`source_url` (or any
other undeclared field) is rejected with `422` (the SSRF boundary: verify takes
identities, the resolver chooses what to fetch).

```json
{ "rows": [{ "row_id": "12", "vendor_name": "Stripe", "domain": "stripe.com" }] }
```

`rows` is bounded by `OPENVA_MAX_VERIFY_ROWS` (default `20`); a request exceeding it
returns `413 row_limit_exceeded` **before any job is created** (a pre-job rejection, never
a job failure code). The response returns the `job_id`, a one-time high-entropy
`job_token`, the initial `state` (`received`), `expires_at`, snapshot provenance, and
`not_advice: true`:

```json
{ "job_id": "…uuid…", "job_token": "…one-time capability…", "state": "received",
  "expires_at": "…Z", "snapshot": { … }, "not_advice": true }
```

The `job_token` is returned **once, here only**. Store it to poll; it is never returned
again, never logged, and only its SHA-256 digest is persisted.

### `GET /v1/verify/{job_id}`
Poll a verify job. The **`job_token` is the sole authorizer** — neither the API key nor
public-read applies. The token must be sent in the `Authorization: Bearer <job_token>`
header **only**; a token in the query string, the URL path, a cookie, or via a redirect
does **not** authenticate. A missing token returns a generic `401`; a wrong token, an
unknown `job_id`, or a non-UUID `job_id` all return the **same** generic `401`
(content-free, no token echo, no existence disclosure — the digest comparison is
constant-time and runs even on not-found). An expired job (now ≥ `expires_at`) returns a
content-free `410`.

On success it returns the job `state`, `row_count`, `created_at`/`updated_at`/`expires_at`,
snapshot, and `not_advice: true`. The `result` field is populated only when the job is
`completed`; `error_code` is set only when `failed`. The response never includes the
token, the token digest, the submitted request content, or the lease fields. (In WP-02A,
with no worker, a polled job remains `received`.)

## Snapshot and refresh

`snapshot.snapshot_digest` is a deterministic `sha256:` digest of the loaded pack;
re-running enrichment after the service loads a newer pack changes the digest. It is a
content snapshot identity, not a git commit SHA. `catalog_commit_sha` is `null` unless
the deployment supplies `OPENVA_CATALOG_COMMIT_SHA`.

## Limitations

Cached only — no live verification. The catalogue covers a curated set of vendors; an
unmatched vendor means OpenVA has no catalogue record, not that the vendor is unsafe.
This endpoint and the MCP `enrich_inventory` tool are the primary, agent-composed way to
consume OpenVA. The Google Sheets client (`integrations/google-sheets/`) is a secondary,
manually installed reference/fallback client; Excel and Word clients are optional
secondary surfaces built only where demand or policy justifies them, not a committed next
step ([ADR-0005](architecture/decisions/ADR-0005-native-clients-as-secondary-compatibility-surfaces.md)).
