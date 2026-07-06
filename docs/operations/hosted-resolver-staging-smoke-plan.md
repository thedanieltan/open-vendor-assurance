# Hosted resolver staging smoke plan

This plan defines the Phase 4 staging acceptance checks for the hosted resolver. It is a
staging evidence contract, not a deployment claim.

OpenVA does not operate a production hosted endpoint until the maintainer-gated staging,
production, and launch-evidence slices are complete. This document records what must pass
when a staging host exists.

## Scope

Phase 4 validates that a staging deployment can expose cached lookup, on-demand source
checks, and async resolver jobs without changing OpenVA's non-advisory boundary.

The staging host must preserve these properties:

- public-source locator metadata only;
- no vendor approval, ranking, scoring, compliance decision, legal opinion, procurement
  recommendation, or security conclusion;
- no raw private evidence storage;
- no request-body, vendor-identity, job-token, or Authorization-header logging;
- live check disabled or honestly degraded when the verify path is unavailable;
- kill switch leaves cached reads available and live verification unavailable;
- static site and static exports remain unaffected.

## Required staging endpoint surface

The roadmap names the public resolver surface in resolver-first terms. The current service
already exposes the `/v1` implementation endpoints. Staging must either expose the roadmap
names directly or document the reverse-proxy/API-gateway mapping that provides them.

| Roadmap endpoint | Current implementation endpoint | Purpose | Required staging verdict |
| --- | --- | --- | --- |
| `POST /resolve` | `POST /v1/check` | Resolve vendor identities and label each result as cached or verified. | Must return a non-advisory result; may honestly degrade to cached mode. |
| `POST /v1/enrich` | `POST /v1/enrich` | Cached batch enrichment for spreadsheets, agents, and documents. | Must return matched/ambiguous/no-match rows with snapshot provenance. |
| `POST /v1/check` | `POST /v1/check` | Direct live-check API over `/v1`. | Must preserve the same result semantics as `/resolve`. |
| `POST /resolve-jobs` | `POST /v1/verify` | Create an async resolver job. | Must require bearer API key and return `job_id`, one-time `job_token`, state, expiry, snapshot, and `not_advice`. |
| `GET /resolve-jobs/{id}` | `GET /v1/verify/{job_id}` | Poll async resolver job status. | Must require `job_token` via `Authorization: Bearer` only; token in query/path/cookie must not authenticate. |
| `GET /resolve-jobs/{id}/results` | `GET /v1/verify/{job_id}` result field | Retrieve completed async job result. | Must not expose request envelope, token digest, lease fields, or submitted vendor rows. |
| `GET /v1/catalog/meta` | `GET /v1/catalog/meta` | Snapshot identity and guarantees. | Must return public-source, metadata-first, non-advisory guarantees. |

If a staging deployment exposes only the `/v1` implementation paths, the Phase 4 evidence
must say so explicitly and mark the resolver-first aliases as not yet externally exposed.
That is acceptable for an internal staging checkpoint, but not for a public launch claim.

## Smoke A — cached source-pack resolution

Request:

```http
POST /resolve
Content-Type: application/json
```

```json
{
  "rows": [
    { "row_id": "stripe", "vendor_name": "Stripe", "domain": "stripe.com" }
  ],
  "source_types": ["dpa", "privacy_notice", "subprocessors_list", "security_page"]
}
```

Expected:

- HTTP `200` when the service is healthy;
- `not_advice: true`;
- advisory-boundary response header set to `non_advisory`;
- snapshot identity present;
- each row has an explicit freshness/mode label;
- matched, ambiguous, and no-match states are not collapsed into one another;
- if live verification is unavailable, the response is labelled cached rather than verified.

## Smoke B — batch enrichment

Request:

```http
POST /v1/enrich
Content-Type: application/json
```

```json
{
  "vendors": [
    { "row_id": "stripe", "vendor_name": "Stripe", "domain": "stripe.com" }
  ],
  "source_types": ["dpa", "privacy_notice", "subprocessors_list", "security_page"]
}
```

Expected:

- HTTP `200`;
- `not_advice: true`;
- snapshot identity present;
- row order preserved;
- source columns are public locator metadata only;
- missing source types are represented as missing/null, never as non-compliance.

## Smoke C — async resolver job lifecycle

Request:

```http
POST /resolve-jobs
Authorization: Bearer <OPENVA_SERVICE_API_KEY>
Content-Type: application/json
```

```json
{
  "rows": [
    { "row_id": "stripe", "vendor_name": "Stripe", "domain": "stripe.com" }
  ],
  "source_types": ["dpa", "privacy_notice"]
}
```

Expected create response:

- HTTP `200` or `202` depending on deployment contract;
- `job_id` returned;
- one-time `job_token` returned only on creation;
- expiry timestamp returned;
- `not_advice: true`;
- no submitted vendor rows echoed in durable metadata.

Poll request:

```http
GET /resolve-jobs/{job_id}
Authorization: Bearer <job_token>
```

Expected poll response:

- HTTP `200` for a live job with the correct token;
- content-free `401` for missing/invalid token;
- content-free `410` for expired-but-retained job;
- content-free `404` for unknown, purged, or invalid job id;
- no token, token digest, request envelope, lease fields, or raw submitted rows in the response.

## Smoke D — source-pack schema compatibility

For every successful `/resolve`, `/v1/check`, or completed async job result used as a public
source pack, the staging evidence must identify how the response maps to
`schemas/openva/source-pack-result.schema.json`.

Required public source-row fields:

```text
match_status
source_type
source_url
result_state
mode
confidence
public_access_status
checked_at
snapshot_id
candidate_queued
not_advice
```

The staging evidence may map internal resolver fields into this public shape, but it must not
publish lifecycle-only internals as user-facing source-pack fields.

## Smoke E — degradation and kill switch

With live verification disabled or kill-switched:

- `/resolve` and `/v1/check` still return cached results when cached data is available;
- responses explicitly label the result as cached or not checked live;
- `/resolve-jobs` either returns a clean disabled response or is unavailable according to
  the deployment contract;
- no stale cached result is labelled as verified;
- `/v1/catalog/meta` remains available.

## Smoke F — privacy and logging

Staging evidence must confirm that logs and telemetry do not contain:

- request bodies;
- vendor names;
- domains submitted by a user;
- registration numbers;
- Authorization headers;
- job tokens;
- job-token digests;
- raw source-pack rows;
- private evidence or documents.

Route-template logs such as `POST /resolve` or `POST /v1/check` are acceptable. Concrete
vendor IDs in URL paths are not acceptable in access logs.

## Evidence bundle

A Phase 4 staging evidence bundle should contain:

```text
staging_base_url
service_version
image_digest or deployment artifact digest
snapshot_id
catalog_commit_sha when configured
public_read_enabled true/false
verify_transport_enabled true/false
verify_kill_switch true/false
allowed_origins
rate_limit policy summary
smoke results A-F
known gaps
not_advice_boundary_confirmed true
```

The evidence bundle must not contain secrets, API keys, job tokens, raw submitted vendor rows,
private documents, or request bodies.

## Non-goals

Phase 4 does not:

- provision production;
- enable public traffic;
- change catalog records;
- create candidate records;
- approve vendors;
- score vendors;
- store private evidence;
- monitor vendor document contents.
