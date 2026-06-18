# OpenVA Match Service

A small, self-hostable FastAPI service that wraps the OpenVA pack reader and vendor
inventory matcher as a read-only HTTP API. It loads one published catalogue pack at
startup and answers identity-match and source-enrichment requests against it.

OpenVA does not operate a central hosted service. This is **cached catalogue
enrichment** — every response reflects the pack loaded at startup. **No source is
fetched or verified live during a request.** Output is non-advisory metadata, not a
compliance, vendor-risk, legal, procurement, or security conclusion.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | none | Liveness |
| GET | `/readyz` | none | Readiness (200 when the pack is loaded) |
| GET | `/pack/meta` | bearer | Pack metadata (unchanged) |
| POST | `/match` | bearer | CSV inventory matching (unchanged) |
| GET | `/v1/catalog/meta` | read | Snapshot identity + manifest guarantees |
| GET | `/v1/vendors/{vendor_id}` | read | One vendor + its canonical sources |
| GET | `/v1/vendors/{vendor_id}/sources` | read | Canonical sources, optional `?source_type=` filter (repeatable) |
| POST | `/v1/match` | read | Resolve one vendor identity (JSON) |
| POST | `/v1/enrich` | read | Enrich a bounded batch of vendor rows (the spreadsheet/document endpoint) |

`read` means: the existing bearer key **unless** `OPENVA_PUBLIC_READ_ENABLED=true`, in
which case the `/v1` read-only endpoints are public. Interactive API docs are at `/docs`
and the schema at `/openapi.json`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `OPENVA_PACK_PATH` | _required_ | Path to the pack directory or its `openva-pack.json` |
| `OPENVA_SERVICE_API_KEY` | _required_ | Bearer key for authenticated endpoints |
| `OPENVA_MAX_UPLOAD_BYTES` | `5000000` | CSV upload byte cap (`/match`) |
| `OPENVA_MAX_REQUEST_BYTES` | = `OPENVA_MAX_UPLOAD_BYTES` | JSON request-body cap for the `/v1` endpoints, enforced at the ASGI boundary before parsing (chunked / no-Content-Length included). Independent of the CSV cap; `/match` is exempt and keeps its own cap. Over-limit → stable `413`. |
| `OPENVA_MAX_ROWS` | `500` | Row cap for `/match` and `/v1/enrich` |
| `OPENVA_PUBLIC_READ_ENABLED` | `false` | When true, `/v1` read endpoints need no key. Read-only only; never enables any write/submission/candidate-intake capability. |
| `OPENVA_ALLOWED_ORIGINS` | _empty_ | Comma-separated CORS origins for browser clients. Empty means no cross-origin origins (never an implicit `*`). Methods limited to GET/POST/OPTIONS; headers to Authorization/Content-Type; credentials disabled. |
| `OPENVA_CATALOG_COMMIT_SHA` | _unset_ | Optional 40-char lowercase hex commit SHA surfaced in `snapshot.catalog_commit_sha`; `null` when unset. Never fabricated. |
| `OPENVA_ACCESS_LOG_ENABLED` | `false` | Whether the bundled launcher enables Uvicorn's request access log. Off by default because default access logs record concrete request targets (e.g. `/v1/vendors/{vendor_id}`), which are submitted vendor identities. |

## Snapshot identity

Every `/v1` catalogue response carries a `snapshot` object: `profile_id`,
`schema_version`, `generated_at`, `vendor_count`, `source_count`, `snapshot_digest`
(a deterministic `sha256:` digest of the loaded pack manifest + referenced index files,
computed once at startup — **not** a git commit SHA), and `catalog_commit_sha`.

## Privacy

The service has no database and persists nothing. Submitted vendor names, domains,
business-entity names, registration numbers, row IDs, source-type selections, and
generated results are used only to answer the request and are never written to disk,
stored in process state, logged in full, or sent to analytics.

Because `/v1/vendors/{vendor_id}` carries a submitted vendor identity in its path, the
bundled launcher disables Uvicorn's request access log by default (`OPENVA_ACCESS_LOG_ENABLED`,
default `false`). If you front the service with your own ASGI server, Gunicorn, or a
reverse proxy, disable raw-path access logging or use route-template / redacted structured
logging, and never log request bodies, query values, or concrete vendor IDs.

## Local development

```bash
pip install -e "services/openva_match_service[dev]"
OPENVA_PACK_PATH=. OPENVA_SERVICE_API_KEY=dev-key openva-match-service
```

Public API usage, request/response shapes, and match-state meanings are documented in
[`docs/resolver-api.md`](../../docs/resolver-api.md).
