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

`X-OpenVA-Pack-Generated-At` mirrors pack metadata. When deterministic builds
use a fixed timestamp such as `1970-01-01T00:00:00Z`, this header is not a
catalog freshness signal.

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
