# OpenVA Match Service Contract

The OpenVA match service is an optional self-hosted HTTP wrapper around the OpenVA pack reader and vendor inventory matcher. It returns public metadata references only. It does not make risk, compliance, approval, or suitability assertions.

OpenVA does not operate a central hosted service. Consumers that want HTTP access run their own service instance from a pinned repository commit or release.

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

Minimum input columns:

```csv
vendor_name,domain,category
Stripe,stripe.com,payments
Slack,slack.com,collaboration
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

## Consumer Migration Notes

Downstream consumers should replace local `OPENVA_PACK_PATH` invocation with `OPENVA_SERVICE_URL` and `OPENVA_SERVICE_API_KEY`, send uploaded inventory CSV files to `POST /match`, and consume matcher fields as native JSON arrays and objects instead of JSON-encoded CSV cell strings.
